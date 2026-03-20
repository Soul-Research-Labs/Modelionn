# Testnet Deployment Guide

Deploy ZKML on Bittensor testnet for development and validation.

## Prerequisites

- Python 3.10+
- Docker & Docker Compose
- A funded testnet wallet (get test TAO from the faucet)

## 1. Create a Wallet

```bash
pip install bittensor
btcli wallet create --wallet-name zkml --wallet-hotkey default
```

## 2. Fund the Wallet

```bash
btcli wallet faucet --wallet-name zkml --subtensor.network test
```

## 3. Register on the Subnet

```bash
python scripts/register.py --network test --wallet-name zkml
```

Or directly:

```bash
btcli subnet register --netuid 1 --subtensor.network test --wallet.name zkml
```

## 4. Start the Registry

```bash
# Set environment
cp .env.example .env
# Edit .env: ZKML_BT_NETWORK=test

# Start all services
docker compose up -d
```

## 5. Run a Miner

```bash
docker build -f docker/Dockerfile.neuron --target miner -t zkml-miner .
docker run --rm \
  --network host \
  -v ~/.bittensor:/root/.bittensor \
  zkml-miner \
  --netuid 1 \
  --subtensor.network test \
  --wallet.name zkml \
  --wallet.hotkey default
```

## 6. Run a Validator

```bash
docker build -f docker/Dockerfile.neuron --target validator -t zkml-validator .
docker run --rm \
  --network host \
  -v ~/.bittensor:/root/.bittensor \
  zkml-validator \
  --netuid 1 \
  --subtensor.network test \
  --wallet.name zkml \
  --wallet.hotkey default
```

## 7. Verify

```bash
# Check registration
python scripts/register.py --network test --wallet-name zkml

# Health check
curl http://localhost:8000/health

# Push a test model
zkml push model ./my-model.bin --name test-model --version 0.1 --hotkey <your-hotkey>
```

## Network Configuration

| Setting                          | Testnet | Mainnet (Finney)         |
| -------------------------------- | ------- | ------------------------ |
| `ZKML_BT_NETWORK`           | `test`  | `finney`                 |
| `ZKML_BT_NETUID`            | `1`     | _your registered netuid_ |
| `ZKML_MIN_STAKE_TO_PUBLISH` | `0.0`   | `100.0`                  |

## Troubleshooting

- **"Not registered"**: Run `scripts/register.py` or `btcli subnet register`
- **"Insufficient stake"**: Get more test TAO via `btcli wallet faucet`
- **Connection errors**: Ensure `--subtensor.network test` is set correctly
