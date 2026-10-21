//go:build linux

package main

import (
	"encoding/binary"
	"errors"
	"io"
	"net"
	"strconv"
	"sync"
	"syscall"
	"time"
)

const laluneSocksMark = 0x4d53

type Socks5Server struct {
	mu   sync.Mutex
	addr string
	ln   net.Listener
}

func NewSocks5Server(addr string) *Socks5Server { return &Socks5Server{addr: addr} }

func (s *Socks5Server) Start() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.ln != nil { return nil }
	ln, err := net.Listen("tcp", s.addr)
	if err != nil { return err }
	s.ln = ln
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil { return }
			go s.handle(c)
		}
	}()
	return nil
}

func (s *Socks5Server) Stop() {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.ln != nil {
		_ = s.ln.Close()
		s.ln = nil
	}
}

func laluneDialer(network string) net.Dialer {
	return net.Dialer{
		Timeout: 15 * time.Second,
		Control: func(_, _ string, rc syscall.RawConn) error {
			var setErr error
			if err := rc.Control(func(fd uintptr) {
				setErr = syscall.SetsockoptInt(int(fd), syscall.SOL_SOCKET, syscall.SO_MARK, laluneSocksMark)
			}); err != nil {
				return err
			}
			return setErr
		},
	}
}

func (s *Socks5Server) dialTCP(addr string) (net.Conn, error) {
	if _, err := net.InterfaceByName("csqtt0"); err != nil {
		return nil, errors.New("LaLune TUN is not active")
	}
	d := laluneDialer("tcp")
	return d.Dial("tcp", addr)
}

func (s *Socks5Server) dialUDP() (*net.UDPConn, error) {
	if _, err := net.InterfaceByName("csqtt0"); err != nil {
		return nil, errors.New("LaLune TUN is not active")
	}
	lc := net.ListenConfig{Control: laluneDialer("udp").Control}
	pc, err := lc.ListenPacket(nil, "udp", "0.0.0.0:0")
	if err != nil { return nil, err }
	return pc.(*net.UDPConn), nil
}

func readSocksAddr(r io.Reader) (string, error) {
	var t [1]byte
	if _, err := io.ReadFull(r, t[:]); err != nil { return "", err }
	var host string
	switch t[0] {
	case 1:
		b := make([]byte, 4)
		if _, err := io.ReadFull(r, b); err != nil { return "", err }
		host = net.IP(b).String()
	case 3:
		var n [1]byte
		if _, err := io.ReadFull(r, n[:]); err != nil { return "", err }
		b := make([]byte, int(n[0]))
		if _, err := io.ReadFull(r, b); err != nil { return "", err }
		host = string(b)
	case 4:
		b := make([]byte, 16)
		if _, err := io.ReadFull(r, b); err != nil { return "", err }
		host = net.IP(b).String()
	default:
		return "", errors.New("unsupported SOCKS address type")
	}
	var p [2]byte
	if _, err := io.ReadFull(r, p[:]); err != nil { return "", err }
	return net.JoinHostPort(host, strconv.Itoa(int(binary.BigEndian.Uint16(p[:])))), nil
}

func writeSocksReply(c net.Conn, code byte, bind net.Addr) error {
	ip := net.IPv4zero
	port := 0
	switch a := bind.(type) {
	case *net.TCPAddr:
		ip, port = a.IP, a.Port
	case *net.UDPAddr:
		ip, port = a.IP, a.Port
	}
	if ip == nil || ip.IsUnspecified() {
		if local, ok := c.LocalAddr().(*net.TCPAddr); ok { ip = local.IP }
	}
	if v4 := ip.To4(); v4 != nil {
		b := []byte{5, code, 0, 1, v4[0], v4[1], v4[2], v4[3], 0, 0}
		binary.BigEndian.PutUint16(b[8:], uint16(port))
		_, err := c.Write(b)
		return err
	}
	if v6 := ip.To16(); v6 != nil {
		b := []byte{5, code, 0, 4}
		b = append(b, v6...)
		b = append(b, 0, 0)
		binary.BigEndian.PutUint16(b[len(b)-2:], uint16(port))
		_, err := c.Write(b)
		return err
	}
	return errors.New("cannot determine SOCKS5 reply address")
}

func (s *Socks5Server) handle(c net.Conn) {
	defer c.Close()
	c.SetDeadline(time.Now().Add(20 * time.Second))

	var h [2]byte
	if _, err := io.ReadFull(c, h[:]); err != nil || h[0] != 5 { return }
	methods := make([]byte, int(h[1]))
	if _, err := io.ReadFull(c, methods); err != nil { return }
	noAuth := false
	for _, method := range methods {
		if method == 0 { noAuth = true; break }
	}
	if !noAuth {
		_, _ = c.Write([]byte{5, 0xff})
		return
	}
	if _, err := c.Write([]byte{5, 0}); err != nil { return }

	var req [3]byte
	if _, err := io.ReadFull(c, req[:]); err != nil || req[0] != 5 { return }

	switch req[1] {
	case 1:
		s.handleConnect(c)
	case 3:
		s.handleUDPAssociate(c)
	default:
		_ = writeSocksReply(c, 7, &net.TCPAddr{})
	}
}

func (s *Socks5Server) handleConnect(c net.Conn) {
	addr, err := readSocksAddr(c)
	if err != nil { _ = writeSocksReply(c, 8, &net.TCPAddr{}); return }
	out, err := s.dialTCP(addr)
	if err != nil { _ = writeSocksReply(c, 1, &net.TCPAddr{}); return }
	defer out.Close()

	c.SetDeadline(time.Time{})
	if err := writeSocksReply(c, 0, out.LocalAddr()); err != nil { return }

	done := make(chan struct{}, 2)
	go func() { _, _ = io.Copy(out, c); done <- struct{}{} }()
	go func() { _, _ = io.Copy(c, out); done <- struct{}{} }()
	<-done
}

func (s *Socks5Server) handleUDPAssociate(c net.Conn) {
	u, err := net.ListenUDP("udp", &net.UDPAddr{IP: net.IPv4zero, Port: 0})
	if err != nil { _ = writeSocksReply(c, 1, &net.TCPAddr{}); return }
	defer u.Close()

	if err := writeSocksReply(c, 0, u.LocalAddr()); err != nil { return }
	c.SetDeadline(time.Time{})

	buf := make([]byte, 65535)
	var client *net.UDPAddr
	for {
		_ = u.SetReadDeadline(time.Now().Add(12 * time.Hour))
		n, src, err := u.ReadFromUDP(buf)
		if err != nil { return }
		if client == nil { client = src }
		if !src.IP.Equal(client.IP) || src.Port != client.Port { continue }
		if n < 7 || buf[0] != 0 || buf[1] != 0 || buf[2] != 0 { continue }

		target, off, err := readUDPAddr(buf[:n], 3)
		if err != nil { continue }
		dst, err := net.ResolveUDPAddr("udp", target)
		if err != nil { continue }

		out, err := s.dialUDP()
		if err != nil { continue }
		_ = out.SetReadDeadline(time.Now().Add(5 * time.Second))
		if _, err = out.WriteToUDP(buf[off:n], dst); err == nil {
			rn, ra, er := out.ReadFromUDP(buf)
			if er == nil {
				packet, buildErr := buildUDPReply(ra, buf[:rn])
				if buildErr == nil {
					_, _ = u.WriteToUDP(packet, client)
				}
			}
		}
		_ = out.Close()
	}
}

func readUDPAddr(b []byte, off int) (string, int, error) {
	if len(b) <= off { return "", 0, io.ErrUnexpectedEOF }
	t := b[off]; off++
	var host string
	switch t {
	case 1:
		if len(b) < off+4 { return "", 0, io.ErrUnexpectedEOF }
		host = net.IP(b[off:off+4]).String(); off += 4
	case 3:
		if len(b) < off+1 { return "", 0, io.ErrUnexpectedEOF }
		n := int(b[off]); off++
		if len(b) < off+n { return "", 0, io.ErrUnexpectedEOF }
		host = string(b[off:off+n]); off += n
	case 4:
		if len(b) < off+16 { return "", 0, io.ErrUnexpectedEOF }
		host = net.IP(b[off:off+16]).String(); off += 16
	default:
		return "", 0, errors.New("unsupported UDP address type")
	}
	if len(b) < off+2 { return "", 0, io.ErrUnexpectedEOF }
	port := int(binary.BigEndian.Uint16(b[off : off+2]))
	return net.JoinHostPort(host, strconv.Itoa(port)), off + 2, nil
}

func buildUDPReply(addr *net.UDPAddr, payload []byte) ([]byte, error) {
	if addr == nil || addr.Port < 0 || addr.Port > 65535 {
		return nil, errors.New("invalid UDP source address")
	}
	var header []byte
	if ip4 := addr.IP.To4(); ip4 != nil {
		header = []byte{0, 0, 0, 1, ip4[0], ip4[1], ip4[2], ip4[3], 0, 0}
	} else if ip6 := addr.IP.To16(); ip6 != nil {
		header = []byte{0, 0, 0, 4}
		header = append(header, ip6...)
		header = append(header, 0, 0)
	} else {
		return nil, errors.New("invalid UDP source IP")
	}
	binary.BigEndian.PutUint16(header[len(header)-2:], uint16(addr.Port))
	return append(header, payload...), nil
}
