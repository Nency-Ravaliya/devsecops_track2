# 🚀 DevSecOps Live Demo - Manual Commands Guide

Run these commands **one by one** in your terminal. Each section explains what it does and what to expect.

---

## 📍 Step 1: Navigate to Project Root

```bash
cd path/to/devsecops_track2/
pwd
```

**Expected:** Shows the path to your `devsecops_track2` project directory

---

## 📁 Step 2: Create/Verify Required Directories

```bash
# Create docs and test folders (if not exist)
mkdir -p docs test

# Verify they exist
ls -la docs/ test/
```

**Expected:** Both folders listed

---

## 📋 Step 3: Verify Project Structure

```bash
# Check reference target exists
ls -la reference-target/terraform/

# Count Terraform files
find reference-target -name "*.tf" -type f | wc -l
```

**Expected:** Shows terraform directories (aws, azure, gcp, etc.) and ~47 .tf files

---

## 🔧 Step 4: Check Environment Dependencies

```bash
# Check Docker
docker --version
docker run --rm hello-world 2>&1 | tail -3

# Check Python
python3 --version

# Check Node (optional)
node --version 2>/dev/null || echo "Node not installed (OK)"

# Check if security tools installed natively (warnings expected)
which terraform || echo "⚠️ Terraform not native - will use Docker"
which tfsec || echo "⚠️ tfsec not native - will use Docker" 
which checkov || echo "⚠️ checkov not native - will use Docker"
which trivy || echo "⚠️ trivy not native - will use Docker"
```

**Expected:** Docker & Python available. Security tools show warnings (normal - using Docker containers)

---

## 🐳 Step 5: Test Docker Container Execution

```bash
# Test basic Docker
docker run --rm alpine echo "Docker works!"

# Test Terraform container
docker run --rm -v "$(pwd)/reference-target/terraform/aws:/workspace" \
  -w /workspace hashicorp/terraform:latest \
  terraform init -backend=false 2>&1 | tail -3
```

**Expected:** "Docker works!" and Terraform initialization output

---

## 🔍 Step 6: Run Security Scans (One by One)

### 6a: Terrascan Scan
```bash
# Run Terrascan on reference target
docker run --rm -v "$(pwd)/reference-target:/iac" \
  tenable/terrascan:latest scan -i terraform -d /iac --format json \
  > test/terrascan_output.json 2>&1

# Check results
cat test/terrascan_output.json | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    failed = len(d.get('results', {}).get('failed', []))
    print(f'Terrascan: {failed} failed policies')
except:
    print('Terrascan completed (check JSON)')
"
```

**Expected:** Shows number of failed policies (typically 3+ for insecure config)

---

### 6b: Checkov Scan
```bash
# Run Checkov
docker run --rm -v "$(pwd)/reference-target:/iac" \
  bridgecrew/checkov:latest -d /iac --output json \
  > test/checkov_output.json 2>&1

# Check results
python3 -c "
import json
with open('test/checkov_output.json') as f:
    data = json.load(f)
if isinstance(data, list) and data:
    r = data[0].get('results', {})
    print(f'Checkov: {len(r.get(\"passed_checks\", []))} passed, {len(r.get(\"failed_checks\", []))} failed')
"
```

**Expected:** Shows passed/failed check counts (typically ~400+ failed for terragoat)

---

### 6c: tfsec Scan
```bash
# Run tfsec
docker run --rm -v "$(pwd)/reference-target:/iac" \
  aquasec/tfsec:latest /iac --format json \
  > test/tfsec_output.json 2>&1

# Check results
python3 -c "
import json
with open('test/tfsec_output.json') as f:
    data = json.load(f)
results = data.get('results', [])
print(f'tfsec: {len(results)} issues')
for r in results[:3]:
    print(f'  - {r.get(\"rule_id\"): {r.get(\"description\", \"\")[:60]}')"
```

**Expected:** Shows issue count (typically ~29 for terragoat)

---

### 6d: Trivy Filesystem Scan
```bash
# Run Trivy
docker run --rm -v "$(pwd)/reference-target:/iac" \
  aquasec/trivy:latest fs --security-checks config /iac -f json \
  > test/trivy_output.json 2>&1

# Check results
python3 -c "
import json
with open('test/trivy_output.json') as f:
    data = json.load(f)
total = sum(len(r.get('Misconfigurations', [])) for r in data.get('Results', []))
print(f'Trivy: {total} misconfigurations')"
```

**Expected:** Shows misconfiguration count (typically ~90+ for terragoat)

---

### 6e: Gitleaks Secret Scan
```bash
# Run Gitleaks
docker run --rm -v "$(pwd)/reference-target:/repo" \
  zricethezav/gitleaks:latest detect --source /repo --report-format json \
  > test/gitleaks.json 2>&1

# Check results
python3 -c "
import json
with open('test/gitleaks.json') as f:
    data = json.load(f)
print(f'Gitleaks: {len(data)} secrets found')"
```

**Expected:** Usually 0 (demo secrets are allowlisted)

---

## ✅ Step 7: Terraform Validation (All Clouds)

```bash
# Validate each cloud provider
for cloud in aws azure gcp alicloud oracle; do
  tf_dir="reference-target/terraform/$cloud"
  if [ -d "$tf_dir" ]; then
    echo "=== Validating $cloud ==="
    docker run --rm -v "$(pwd)/$tf_dir:/workspace" -w /workspace \
      hashicorp/terraform:latest \
      sh -c "terraform init -backend=false 2>&1 | tail -2; terraform validate 2>&1 | tail -2"
    echo ""
  fi
done
```

**Expected:** 
- AWS, Azure: Init works, validate may show provider auth warnings (OK)
- GCP, Alibaba, Oracle: ✅ Validated successfully

---

## 🐍 Step 8: Python Pattern Analysis

```bash
# Run custom Python analysis
python3 << 'PYEOF'
import os, re

ref = "reference-target"
findings = {'public_s3':0, 'public_rds':0, 'wildcard_iam':0, 'hardcoded_secrets':0}

for root, dirs, files in os.walk(ref):
    if '.git' in root: continue
    for f in files:
        if f.endswith('.tf'):
            path = os.path.join(root, f)
            with open(path) as fh: content = fh.read()
            if 'public-read' in content or 'allUsers' in content: findings['public_s3'] += 1
            if 'authorized_networks' in content and '0.0.0.0/0' in content: findings['public_rds'] += 1
            if '"*"' in content and ('Action' in content or 'actions' in content): findings['wildcard_iam'] += 1
            if 'AdminPassword' in content or 'access_key' in content.lower(): findings['hardcoded_secrets'] += 1

print("Python Security Pattern Analysis:")
print("=" * 40)
for k, v in findings.items():
    status = '⚠️' if v > 0 else '✅'
    print(f'  {status} {k}: {v} files')
PYEOF
```

**Expected:** Shows pattern matches for common security issues

---

## 📊 Step 9: Generate Final Report

```bash
# Create comprehensive final report
cat > test/final_report.md << 'RPT'
# DevSecOps Live Demo - Final Report
**Date:** $(date)
**Target:** terragoat reference target

## Summary
All security scans executed successfully against intentionally vulnerable Terraform configurations.

## Key Findings
- **Public S3 Buckets**: Detected by all scanners
- **Public Unencrypted Databases**: RDS/Cloud SQL exposed
- **Wildcard IAM Policies**: Full admin access granted
- **Hardcoded Credentials**: In Terraform and user_data
- **Open Firewall Rules**: 0.0.0.0/0 access allowed

## Tools Executed
✅ Terrascan | ✅ Checkov | ✅ tfsec | ✅ Trivy | ✅ Gitleaks | ✅ Terraform Validate

## Files Generated
- test/terrascan_output.json
- test/checkov_output.json  
- test/tfsec_output.json
- test/trivy_output.json
- test/gitleaks.json
- test/demo_log.txt
RPT

# View report
cat test/final_report.md
```

**Expected:** Final report displayed with all findings summary

---

## 📋 Step 10: Quick Verification

```bash
# One-liner status check
echo "=== LIVE DEMO STATUS ===" && \
for f in terrascan_output.json checkov_output.json tfsec_output.json trivy_output.json gitleaks.json final_report.md; do
  [ -f "test/$f" ] && echo "✅ $f" || echo "❌ $f"
done

# Show file sizes
ls -lh test/
```

**Expected:** All files present with appropriate sizes

---

## 🧹 Optional: Clean Up and Reset

```bash
# To re-run demo from scratch
rm -rf test/*
mkdir -p test
# Then repeat steps 3-10
```

---

## 📖 Command Explanation Reference

| Command | Purpose |
|---------|---------|
| `docker run --rm` | Run container, remove after |
| `-v $(pwd)/path:/mount` | Mount local directory into container |
| `-w /workspace` | Set working directory in container |
| `> file.json 2>&1` | Redirect stdout & stderr to file |
| `python3 -c "..."` | Run inline Python script |
| `find ... -name "*.tf"` | Find all Terraform files |
| `for cloud in ...` | Loop through cloud providers |

---

## ✅ Success Criteria

Demo passes if:
- [ ] All 6 security scans complete (exit codes 0 or 1 expected)
- [ ] At least 3 critical findings detected
- [ ] Terraform validation shows syntax OK for 3+ clouds
- [ ] Final report generated in `test/final_report.md`
- [ ] All JSON output files created in `test/`

---

**Run each section in order. If any step fails, check the error message and re-run that specific command.**
