# Journey Diagnosis Playbook

Never add Meta leads and GA4 conversions as one total.

Use differences between Meta and GA4 as tracking or attribution signals:
- click-to-session loss can indicate redirects, UTMs, page load, or attribution issues.
- engaged sessions with low conversions can indicate offer, CTA, or form friction.
- pixel-GA4 gaps can indicate duplicate tracking, missing events, or attribution differences.

Ad-level conclusions require reliable matching such as ad_id or campaign_id in GA4. Without it, stay at campaign/source level.

Strong matching requires UTM fields plus a stable identifier such as ad_id or campaign_id.
If the UTM audit fails, recommend Fix Tracking before Scale, Stop, or ad-level budget changes.
