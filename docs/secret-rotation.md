# Secret Rotation Runbook

Procedure for rotating secrets in the ZKML registry.

## Webhook Signing Secrets

Webhook secrets are per-webhook and used for HMAC-SHA256 signing.

### API Rotation

```bash
# Rotate via the REST API (returns the new secret once)
curl -X POST https://api.zkml.io/webhooks/{webhook_id}/rotate-secret \
  -H "x-hotkey: $HOTKEY" \
  -H "x-signature: $SIGNATURE" \
  -H "x-nonce: $(uuidgen)" \
  -H "x-timestamp: $(date -u +%s)"
```

### After Rotation

1. Update the receiving endpoint to accept the new signature.
2. Old signatures will immediately stop validating.
3. There is **no grace period** — rotate during a maintenance window or implement dual-signature validation on the receiver side.

## Database Encryption Key (`ZKML_DB_ENCRYPTION_KEY`)

See [encryption-key-management.md](encryption-key-management.md) for the full procedure.

**Summary:**

1. Generate new key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
2. Set `ZKML_DB_ENCRYPTION_KEY_NEW` in environment.
3. Run `python -m cli.main rotate-encryption-key` to re-encrypt all sensitive columns.
4. Swap: rename `_NEW` → primary, remove old key.
5. Restart all app replicas.

## JWT / NextAuth Secret (`NEXTAUTH_SECRET`)

1. Generate: `openssl rand -base64 32`
2. Update the `NEXTAUTH_SECRET` environment variable on all web replicas.
3. Restart web pods — all existing sessions will be invalidated.

## Redis Password

1. Update `REDIS_PASSWORD` in the Docker secret / env source.
2. Restart Celery workers and the API server.
3. Monitor `registry.tasks.webhook_delivery` logs for connection errors.

## Bittensor Wallet Keys

Wallet coldkey/hotkey rotation is managed by the Bittensor SDK. See [subnet-operations.md](subnet-operations.md).

> **Tip:** Schedule secret rotations quarterly and after any personnel change.
