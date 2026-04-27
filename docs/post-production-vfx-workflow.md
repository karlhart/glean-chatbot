# Post-Production & VFX Workflow
**Lumina Stream Studios | Post-Production**
**Version 5.2 | Effective April 2025**

---

## Overview

Post-production at Lumina is tracked in **Jira** (project management) and documented in **Confluence** (process wiki). This document covers the end-to-end post workflow from picture wrap to final delivery.

---

## Jira: Post-Production Project Structure

Every production receives a Jira project upon handoff from production. Jira projects follow the naming convention: `POST-[SHOW-CODE]` (e.g., `POST-LS024`).

### Jira Boards

| Board | Owner | Purpose |
|---|---|---|
| Editorial | Post Supervisor | Cut status, editorial milestones |
| VFX | VFX Supervisor | Shot tracking, vendor assignments |
| Color & Finishing | Colorist / DI Supervisor | Grading passes, QC rounds |
| Audio | Sound Supervisor | Mix stages, M&E delivery |
| Deliverables | Post Coordinator | Final package tracking |

### Standard Jira Issue Types

- **Epic**: Major milestone (e.g., "Episode 3 — Locked Picture")
- **Story**: Deliverable or workflow phase (e.g., "VFX Shot LS024-0342 — Composite")
- **Task**: Granular action item
- **Bug**: QC failure or technical issue requiring remediation

### Jira Custom Fields for VFX

Each VFX shot issue includes:
- `Shot ID` — unique identifier (show code + shot number)
- `Vendor` — assigned VFX house
- `Complexity` — Simple / Medium / Complex / Hero
- `Frames` — frame count
- `On-Screen Duration` — seconds
- `Status` — Concept / WIP / Client Review / Approved / Delivered
- `Deadline` — per the VFX schedule

---

## Editorial Workflow

### Phase 1: Rough Assembly
- Editor receives dailies from production (DIT-processed files via Aspera or ShotGrid)
- Assembly cut completed within **2 weeks** of picture wrap
- Assembled cut shared with Director and EP via Frame.io

### Phase 2: Director's Cut
- Director has **10 business days** (SAG-AFTRA/DGA contractual minimum for episodic)
- Director's Cut reviewed in a supervised screening with EP

### Phase 3: Producer's Cut
- EP has **15 business days** for creative review
- Changes tracked in Frame.io comments; Editor implements via Avid Media Composer
- VFX pull list generated after Producer's Cut lock

### Phase 4: Locked Picture
- All creative changes must be approved by EP and Studio before lock
- Jira Epic "Locked Picture" marked complete; locked picture EDL exported
- Color, audio, VFX, and legal all work from the locked cut

---

## VFX Pipeline

### VFX Supervision
- VFX Supervisor is responsible for shot assignments, vendor management, and client approvals
- VFX budget is tracked in a separate Finance spreadsheet (Box: `/Post-Production/VFX Budget Tracking`)

### Vendor Assignments
Lumina works with a preferred vendor list (updated annually by the VFX Supervisor):
- **Hero/Complex shots**: Assigned to Tier 1 vendors (e.g., MPC, Framestore, Digital Domain)
- **Medium shots**: Tier 2 boutique vendors
- **Simple shots**: In-house compositing (if applicable)

All vendor agreements executed by BA before any creative work begins.

### Shot Review Process
1. Vendor submits shot to Lumina's **ShotGrid** review environment
2. VFX Supervisor reviews; feedback logged in ShotGrid and mirrored to Jira
3. Maximum **3 rounds** of revisions before additional costs are assessed
4. Upon approval, vendor delivers final plate to Lumina's master delivery server (Aspera)

### VFX Confluence Documentation
Confluence (Space: `VFX-[SHOW-CODE]`) contains:
- Shot list (synced from Jira)
- Technical specs per vendor
- Pipeline guides (software versions, color space requirements, file naming)
- Post-mortem notes (lessons learned, archived after delivery)

---

## Color & DI

- Grading platform: **DaVinci Resolve** (in-house DI suite, LA)
- Color space: Rec.2020 / PQ for HDR deliverables; Rec.709 for SDR
- All grades reviewed with the Director and DP present (minimum: one supervised HDR pass)
- Legal QC of color is performed by an approved QC house (see Deliverables section)

---

## Audio Post

### Stages
1. **Dialogue Edit & ADR** — Production dialogue cleaned; ADR recorded and cut
2. **Sound Design** — Ambience, effects, Foley
3. **Temp Mix** — For internal screenings and marketing
4. **Final Mix** — Theatrical (Dolby Atmos where applicable) and streaming (Dolby Digital 5.1 + stereo)

### M&E (Music & Effects)
- M&E stems required for all international deliveries
- M&E must be clean (no dialogue bleed)
- Delivered alongside final mix as part of the master package

---

## Deliverables & QC

### QC Process
1. Internal QC by Post Coordinator (technical check: codec, frame rate, aspect ratio, loudness)
2. External QC by approved QC house (Aris, Deluxe, or Iron Mountain)
3. QC report issued; any QC failures logged as Jira Bugs with priority levels (P1–P3)
4. P1 (critical) issues must be resolved before delivery; P2/P3 can be waived by Distribution VP

### Standard Delivery Formats

| Destination | Format | Frame Rate | Audio |
|---|---|---|---|
| Lumina+ (streaming) | IMF (SMPTE 2067) | Native (23.976 or 25fps) | Dolby Atmos + 5.1 |
| Broadcast partners | ProRes 4444 XQ or AS-11 | Per territory spec | Stereo + 5.1 |
| Theatrical (limited) | DCP | 24fps | Dolby Atmos |
| International co-producers | Per co-production tech specs | As agreed | M&E + Dub stems |

---

## Archive

After final delivery, all post assets are archived per the Lumina Asset Retention Policy:
- Picture elements: **25 years**
- Audio stems: **25 years**
- VFX project files: **10 years**
- Working/offline editorial: **5 years**

Archives managed by Iron Mountain and catalogued in the Lumina Archive Database (contact: postops@luminastreamstudios.com).
