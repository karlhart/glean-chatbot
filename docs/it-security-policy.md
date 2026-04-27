# IT Security & Access Control Policy
**Lumina Stream Studios | Information Technology**
**Version 6.1 | Effective January 2025**

---

## Purpose

This policy establishes minimum security standards for all employees, contractors, and third parties who access Lumina Stream Studios systems and data. Compliance is mandatory. Violations may result in disciplinary action up to and including termination.

---

## Identity & Authentication

### Single Sign-On (SSO)
Lumina uses **Okta** as its identity provider (IdP). All corporate applications are integrated with Okta SSO where technically feasible. Employees must not create separate usernames/passwords for SSO-integrated applications.

**Okta-integrated systems include**: Google Workspace, Slack, Box, Jira, Confluence, Workday, Glean, Frame.io, ShotGrid, Expensify, Concur.

### Multi-Factor Authentication (MFA)
MFA is required for **all accounts** accessing Lumina systems:
- Preferred: Okta Verify (push notification or TOTP)
- Backup: Yubikey hardware token (available from IT for high-risk roles)
- SMS-based MFA is **not permitted** due to SIM-swap risk

### Password Policy
For applications not yet SSO-integrated, passwords must:
- Be at least **16 characters**
- Contain uppercase, lowercase, numbers, and symbols
- Not be reused across systems or from the previous 24 passwords
- Be changed immediately upon any suspected compromise

Use the company-provided password manager (1Password Teams) — licenses available via IT Help Desk.

---

## Device Security

### Corporate Devices
- All corporate laptops are enrolled in **Jamf** (macOS) or **Microsoft Intune** (Windows)
- Full-disk encryption is mandatory (FileVault for Mac, BitLocker for Windows)
- Screen lock activates after **5 minutes** of inactivity
- Auto-updates are managed by IT; employees must not defer OS or security updates beyond 72 hours

### Personal Devices (BYOD)
- Personal devices may not access Lumina corporate systems except via browser-based SSO
- No corporate data (scripts, contracts, unreleased content) may be downloaded to personal devices
- Camera and microphone access on personal devices requires explicit approval from the CISO for sensitive roles

### Lost or Stolen Devices
Report immediately to IT Help Desk (helpdesk@luminastreamstudios.com or Slack #it-support). All corporate devices can be remotely wiped. Do not attempt recovery yourself.

---

## Data Classification

| Classification | Examples | Handling |
|---|---|---|
| **Public** | Press releases, published content | No restrictions |
| **Internal** | Policies, org charts, general comms | Lumina employees only |
| **Confidential** | Scripts, budgets, contracts, talent deals | Named sharing only; no external link sharing |
| **Restricted** | M&A discussions, unreleased trailers, legal privilege | Need-to-know; encrypted storage required |

All new documents created in Google Drive or Box should be labeled with the appropriate classification using the Data Classification tag (available in Google Drive via the Lumina Drive plugin).

---

## Network & Remote Access

### VPN
- **GlobalProtect VPN** is required for access to on-premises systems (edit suites, render farm, archive servers)
- VPN is not required for cloud applications (Google, Slack, Box, Jira, Glean) when using Okta SSO
- Split-tunnel VPN is used — only on-prem traffic routes through VPN

### Wi-Fi
- Use only Lumina corporate Wi-Fi (SSID: `Lumina-Corp`) or a trusted home network
- Public/hotel Wi-Fi requires VPN to be active for all Lumina work
- Guest Wi-Fi (`Lumina-Guest`) is strictly for non-Lumina devices and personal use

---

## Third-Party & Vendor Access

All vendors and contractors requiring Lumina system access must:
1. Sign the Lumina Vendor Security Agreement (managed by Legal/BA)
2. Complete the Vendor Security Assessment questionnaire (managed by IT Security)
3. Access systems via dedicated contractor accounts (never share employee credentials)
4. Be provisioned with **least-privilege access** — only what is strictly necessary for their role

Vendor access is reviewed quarterly by IT Security. Access is revoked immediately upon contract end.

---

## Acceptable Use

### Permitted
- Work-related use of all Lumina-provisioned tools
- Limited personal use that does not impact productivity or security

### Prohibited
- Accessing, storing, or transmitting Lumina content on personal cloud storage (iCloud, personal Google Drive, Dropbox)
- Sharing login credentials with anyone, including colleagues
- Installing unauthorized software on corporate devices (submit IT Help Desk ticket for software requests)
- Using AI tools (ChatGPT, Gemini, etc.) to input confidential scripts, contracts, or talent information — approved AI tools only (Glean AI, approved Microsoft Copilot deployment)
- Circumventing security controls (VPN, MFA, device management)

---

## Incident Response

### What Constitutes a Security Incident?
- Suspected phishing or credential compromise
- Unauthorized access to Lumina systems
- Lost or stolen device
- Accidental sharing of confidential data
- Malware or ransomware detection

### How to Report
1. **Immediately**: Notify IT Security via Slack #security-incidents or security@luminastreamstudios.com
2. Do not attempt to investigate or remediate yourself
3. Preserve evidence — do not delete emails, logs, or messages
4. IT Security will engage the Incident Response team within 1 hour (critical) or 4 hours (non-critical)

Response SLAs:
- **Critical** (active breach, data exfiltration): 1-hour response, 4-hour containment target
- **High** (compromised credentials, lost device): 4-hour response
- **Medium/Low** (phishing attempt, policy violation): Next business day

---

## Compliance & Audits

Lumina is subject to:
- **SOC 2 Type II** (annual audit by external auditor)
- **GDPR** (EU personal data of employees, talent, and users)
- **CCPA** (California consumer data)
- **Content Security** requirements from major streaming partners (Netflix, Apple TV+, Amazon compliance programs)

IT Security conducts quarterly internal audits and annual penetration tests. Employees must cooperate with audit requests within 5 business days.

---

## Contact

- IT Help Desk: helpdesk@luminastreamstudios.com | Slack: #it-support | Phone: ext. 5000
- IT Security: security@luminastreamstudios.com | Slack: #security-incidents
- CISO: Marcus Webb | mwebb@luminastreamstudios.com
