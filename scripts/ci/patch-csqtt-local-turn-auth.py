#!/usr/bin/env python3
"""Apply an ephemeral, CI-only local TURN credential hook to pinned upstream source.

This script is intended only for the disposable GitHub Actions checkout. It does
not modify the upstream repository or any installed/production client.
"""
from pathlib import Path

path = Path("upstream-csqtt-core/rust-client/auth.rs")
source = path.read_text(encoding="utf-8")
marker = '    pub async fn get_credentials(&self, link: &str, stream_id: usize) -> Result<TurnCredentials> {'
if source.count(marker) != 1:
    raise SystemExit("Expected exactly one VkAuth::get_credentials insertion point; refusing patch")

hook = marker + '''
        // Test harness only: local deterministic TURN credentials. The workflow
        // sets all three variables explicitly; normal runs without them follow
        // the untouched VK authentication path. Never log credential values.
        if let (Ok(username), Ok(password), Ok(server)) = (
            std::env::var("CSQTT_TEST_TURN_USERNAME"),
            std::env::var("CSQTT_TEST_TURN_PASSWORD"),
            std::env::var("CSQTT_TEST_TURN_SERVER"),
        ) {
            if !username.is_empty() && !password.is_empty() && !server.is_empty() {
                return Ok(TurnCredentials {
                    username: Arc::from(username),
                    password: Arc::from(password),
                    server_addresses: vec![Arc::<str>::from(server)].into(),
                });
            }
        }
'''
path.write_text(source.replace(marker, hook, 1), encoding="utf-8")
print("Applied ephemeral local TURN credential hook; values were not read or printed.")
