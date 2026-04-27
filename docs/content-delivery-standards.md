# Content Delivery & Streaming Standards
**Lumina Stream Studios | Technology & Distribution**
**Version 3.3 | Effective April 2025**

---

## Overview

This document defines the technical delivery specifications for all Lumina Stream Studios original content delivered to Lumina+ (our owned streaming platform) and to third-party distribution partners.

---

## Lumina+ Platform Specifications

### Video

| Parameter | Specification |
|---|---|
| Container | IMF (Interoperable Master Format, SMPTE ST 2067) |
| Video Codec | JPEG 2000 (IMF CPL) |
| Resolution | 4K UHD (3840×2160) preferred; 1080p minimum |
| Frame Rate | Native production frame rate (23.976, 25, or 29.97fps) |
| Color Space | BT.2020 |
| HDR Standard | Dolby Vision (preferred) + HDR10 (mandatory) |
| Aspect Ratio | 2.39:1 or 1.78:1 (16:9) |
| Bit Depth | 16-bit |

### Audio

| Parameter | Specification |
|---|---|
| Primary | Dolby Atmos (ADM BWF) |
| Fallback | 5.1 surround + stereo mixdown |
| Sample Rate | 48kHz |
| Bit Depth | 24-bit |
| Loudness | -24 LKFS integrated (±1 LU tolerance) per ATSC A/85 |
| M&E | Required; must be clean (no dialogue bleed) |

### Subtitles & Accessibility

- **Closed Captions (CC)**: SRT or IMSC1 (TTML) format, English mandatory
- **SDH** (Subtitles for the Deaf and Hard of Hearing): Required for all territories
- **Audio Description (AD)**: Required for content on Lumina+ per ADA and CVAA compliance
- **Subtitle languages**: As specified per territory in the distribution agreement

---

## Encoding & Streaming (Lumina+ Platform)

Lumina's CDN and transcoding infrastructure (AWS MediaConvert + CloudFront) handles transcoding from the IMF master into adaptive bitrate (ABR) packages:

| Profile | Resolution | Target Bitrate |
|---|---|---|
| 4K HDR | 3840×2160 | 15–20 Mbps |
| 1080p HDR | 1920×1080 | 8–12 Mbps |
| 1080p SDR | 1920×1080 | 5–8 Mbps |
| 720p | 1280×720 | 3–5 Mbps |
| 480p | 854×480 | 1.5–3 Mbps |
| Audio only | — | 192 kbps |

Streaming protocol: **MPEG-DASH** (primary) + **HLS** (Apple devices). DRM: **Widevine** (Android/Web), **FairPlay** (Apple), **PlayReady** (Windows/Xbox).

---

## Third-Party Broadcast Delivery Specifications

### Broadcast (US & International)

| Parameter | Specification |
|---|---|
| Container | MXF (AS-11 for European broadcast; QuickTime/ProRes for US) |
| Video Codec | Apple ProRes 4444 XQ (preferred) or ProRes 422 HQ |
| Resolution | 1080i (interlaced) or 1080p per broadcaster spec |
| Frame Rate | 25fps (PAL territories), 29.97fps (NTSC territories) |
| Audio | Stereo + 5.1 embedded in track layout per broadcaster spec |
| Loudness | -23 LUFS (EBU R128) for international; -24 LKFS (ATSC A/85) for US |

Broadcaster-specific delivery requirements are documented in the **Broadcast Tech Specs Library** (Confluence Space: `DIST-TECHSPECS`).

### OTT Partners (Netflix, Apple TV+, Amazon, etc.)

Each major OTT partner has their own proprietary delivery specification. Lumina's post-production team is responsible for confirming specs before the DI session:
- **Netflix**: Refer to Netflix Originals Delivery Specifications (Netflix partner portal; credentials in IT Vault)
- **Apple TV+**: Apple Mastering Requirements (AMR); contact your Apple partner manager for latest version
- **Amazon Prime Video**: Amazon Video Direct (AVD) specifications (Amazon Partner Central)

**Important**: OTT partner specs change periodically. Always verify the current version before beginning post-production. Do not rely on cached copies older than 6 months.

---

## Metadata & Asset Delivery

Along with the video/audio master, all deliveries must include:

### Required Metadata
- Title, episode number, season number
- Series synopsis and episode logline (English + local language per territory)
- Cast and crew credits (in delivery-ready format per partner spec)
- Content rating and advisory information (per territory classification body)
- Release date and embargo information

### Required Assets
- **Key Art**: Horizontal (16:9) and Vertical (2:3 / 9:16) in specified resolutions
- **Stills**: On-set photography (minimum 20 approved stills per episode)
- **Trailer/Promo**: 30-second, 60-second, and 2-minute cuts (if contracted)
- **Press Kit**: Including EPK (Electronic Press Kit) for PR use

Assets delivered to Lumina's Asset Management System (Bynder) by the Marketing team.

---

## Delivery Timelines

| Deliverable | Deadline |
|---|---|
| QC-approved IMF master | 6 weeks before platform launch |
| Broadcast files (US) | 4 weeks before air date |
| Broadcast files (International) | Per territory distribution agreement |
| Subtitles/CC (English) | 5 weeks before launch |
| Subtitles/CC (other languages) | 3 weeks before launch |
| Key art | 8 weeks before launch (for marketing use) |
| EPK / press materials | 6 weeks before launch |

Late deliveries must be escalated to the Distribution VP immediately. Penalties may apply per distribution agreements.

---

## Content Security (Piracy Prevention)

All post-production facilities and vendors handling Lumina content must comply with:
- **TPN (Trusted Partner Network)** certification — mandatory for all facilities handling 4K or HDR masters
- **Forensic watermarking**: Applied to all screeners and pre-release content (Lumina uses Civolution/NexGuard)
- **Screener distribution**: Pre-release screeners distributed only via approved platform (currently Shift72 / Lumina internal screener system); no physical DVDs or unencrypted downloads

Report suspected piracy immediately to security@luminastreamstudios.com and the Content Security team.

---

## Contacts

- Post-Production Delivery: postdelivery@luminastreamstudios.com
- Distribution Technology: disttech@luminastreamstudios.com
- Platform Engineering (Lumina+): platform@luminastreamstudios.com
- Content Security: security@luminastreamstudios.com
