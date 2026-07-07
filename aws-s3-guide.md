# Connecting to the `moine-data` S3 Bucket

This guide explains how to install the AWS CLI and use it to read/write files in the
**`moine-data`** S3 bucket. Works on **Windows** and **macOS**.

> These credentials only grant access to the `moine-data` bucket — nothing else in the
> AWS account.

---

## Bucket details

| Setting | Value |
|---------|-------|
| Bucket name | `moine-data` |
| Region | `us-east-1` |
| Profile name (used in commands below) | `moine` |

You will be given two secrets **separately** (never commit these to git):

- `AWS Access Key ID` — looks like `AKIA...`
- `AWS Secret Access Key` — a 40-character string

---

## 1. Install the AWS CLI

### Windows

**Option A — winget (recommended):**
```powershell
winget install --id Amazon.AWSCLI
```

**Option B — MSI installer:**
Download and run: https://awscli.amazonaws.com/AWSCLIV2.msi

After installing, **close and reopen** your terminal, then verify:
```powershell
aws --version
```
You should see something like `aws-cli/2.x.x ...`.

### macOS

**Option A — official installer (recommended):**
```bash
curl "https://awscli.amazonaws.com/AWSCLIV2.pkg" -o "AWSCLIV2.pkg"
sudo installer -pkg AWSCLIV2.pkg -target /
```

**Option B — Homebrew:**
```bash
brew install awscli
```

Verify:
```bash
aws --version
```

---

## 2. Configure credentials (one-time)

Run this and paste the values you were given. Using a named profile (`moine`) keeps these
keys separate from any other AWS setup you might have.

**Windows (PowerShell) and macOS (Terminal)** — same command:
```bash
aws configure --profile moine
```
You'll be prompted for four things:
```
AWS Access Key ID [None]:     AKIA...        <- paste the Access Key ID
AWS Secret Access Key [None]: ************   <- paste the Secret Access Key
Default region name [None]:   us-east-1
Default output format [None]: json
```

This saves the profile to:
- Windows: `C:\Users\<you>\.aws\credentials`
- macOS: `~/.aws/credentials`

### Verify it works
```bash
aws sts get-caller-identity --profile moine
```
Expected output (the user ARN should end in `moine-data-user`):
```json
{
    "UserId": "...",
    "Account": "972999821107",
    "Arn": "arn:aws:iam::972999821107:user/moine-data-user"
}
```

---

## 3. Everyday usage

> Add `--profile moine` to every command. (Or set it once per session — see tip below.)

### List files in the bucket
```bash
aws s3 ls s3://moine-data --profile moine
```
List a "folder" (prefix) recursively, with a size summary:
```bash
aws s3 ls s3://moine-data --recursive --summarize --profile moine
```

### Upload a file
```bash
# Windows
aws s3 cp "C:\path\to\file.md" s3://moine-data/file.md --profile moine

# macOS
aws s3 cp "/path/to/file.md" s3://moine-data/file.md --profile moine
```

Upload into a folder/prefix:
```bash
aws s3 cp report.csv s3://moine-data/reports/2026/report.csv --profile moine
```

### Upload a whole folder
```bash
aws s3 cp ./mydir s3://moine-data/mydir --recursive --profile moine
```

### Download a file
```bash
aws s3 cp s3://moine-data/file.md ./file.md --profile moine
```

### Download a whole folder
```bash
aws s3 cp s3://moine-data/reports ./reports --recursive --profile moine
```

### Sync a local folder up to the bucket (only changed files)
```bash
aws s3 sync ./localdir s3://moine-data/localdir --profile moine
```

### Sync from the bucket down to a local folder
```bash
aws s3 sync s3://moine-data/localdir ./localdir --profile moine
```

### Delete a file
```bash
aws s3 rm s3://moine-data/file.md --profile moine
```

---

## Tip: avoid typing `--profile moine` every time

**Windows (PowerShell)** — set for the current session:
```powershell
$env:AWS_PROFILE = "moine"
# now you can omit --profile, e.g.:
aws s3 ls s3://moine-data
```

**macOS / Linux (bash/zsh)** — set for the current session:
```bash
export AWS_PROFILE=moine
aws s3 ls s3://moine-data
```
To make it permanent on macOS, add that `export` line to `~/.zshrc` (or `~/.bashrc`).

---

## What you CAN and CANNOT do with these credentials

✅ **Allowed** (inside `moine-data` only):
- List the bucket contents
- Upload / download / delete objects

❌ **Not allowed:**
- `aws s3 ls` with no bucket (listing *all* buckets) — this will fail with `AccessDenied`.
  That's expected. Always specify the bucket: `aws s3 ls s3://moine-data`.
- Accessing any other bucket
- Any non-S3 service (IAM, EC2, etc.)

---

## Troubleshooting

| Symptom | Cause / Fix |
|---------|-------------|
| `aws: command not found` | CLI not installed or terminal not restarted. Reinstall (Step 1) and reopen the terminal. |
| `AccessDenied` on `aws s3 ls` (no bucket) | Normal — you can't list all buckets. Use `aws s3 ls s3://moine-data`. |
| `AccessDenied` on `moine-data` actions | Wrong/expired keys, or `--profile moine` missing. Re-check Step 2. |
| `InvalidAccessKeyId` / `SignatureDoesNotMatch` | Keys typed/copied wrong. Re-run `aws configure --profile moine`. |
| `Could not connect to the endpoint URL` | Network/proxy issue, or wrong region. Region must be `us-east-1`. |

---

## Security notes

- **Never commit** your access keys to git or share them in chat/email plaintext.
- The keys live in `~/.aws/credentials` — keep that file private.
- If a key is ever exposed, ask the account owner to **rotate** it (deactivate the old key,
  issue a new one).
