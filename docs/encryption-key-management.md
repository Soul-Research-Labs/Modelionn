# Encryption Key Management

`ZKML_ENCRYPTION_KEY` is used for encrypted fields and must be protected as a production secret.

## Generate Key

```bash
python3 - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
```

## Storage Requirements

- Store in a managed secret store (Vault, AWS Secrets Manager, etc.).
- Never commit key values to git.
- Restrict read access to runtime services only.

## Rotation Procedure

1. Announce maintenance window.
2. Deploy application support for dual-key decrypt (old+new) if needed.
3. Re-encrypt data with new key.
4. Remove old key from runtime after verification.

## Lost Key Recovery

If key is lost and no backup exists, encrypted fields are unrecoverable.
Treat key backup and rotation logs as critical compliance artifacts.
