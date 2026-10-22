# Report review

## Summary

The report is organized clearly and gives a useful overview of the recognition workflow, relevant literature, limitations, and future work. It is appropriately transparent that no formal accuracy benchmark has been completed. The project directory contains a working FastAPI dashboard that is more advanced than several parts of the report describe.

## Corrections to make before submission

1. **Bring the report into line with the implementation.** The report says a web front end is future work, while the project already has a FastAPI web dashboard. It also describes processing every fifth frame; the dashboard sends a frame about every 280 ms. Update the architecture, interface, and performance descriptions to match the version being submitted.
2. **Clarify what was actually measured.** The results chapter mostly documents expected behavior and arithmetic derived from the frame skip setting. Label these as functional observations or calculated values, and avoid implying measured recognition accuracy or measured runtime. Keep the explicit note that accuracy evaluation remains future work.
3. **Tighten the claim about the threshold.** A cosine-distance cutoff of 0.4 is a configurable starting point, not evidence of accuracy or a generally conservative setting. Describe how the threshold should be evaluated on genuine and impostor samples from the intended camera and users.
4. **Correct the confidence wording.** The dashboard's displayed confidence is derived from `1 - cosine distance`; it is not a calibrated probability that a match is correct.
5. **Review the certificate wording and dates.** The certificate sentence “has not been previously formed the basis” is grammatically incorrect. The guide's date is blank, while the cover is dated October 2026; complete signature/date fields only after approval by the guide.
6. **Update privacy/legal context.** The report cites the DPDP Act but should explain that commencement is phased. MeitY's November 2025 notification schedules the main processing provisions for 18 months after publication (May 2027), with other provisions on earlier dates; recheck the official timeline at submission. [MeitY commencement notification](https://www.meity.gov.in/static/uploads/2025/11/c56ceae6c383460ca69577428d36828b.pdf)
7. **Add deployment-specific controls and caveats.** State that browser camera access requires HTTPS on a remote host; specify consent/notice, access restrictions, retention and deletion, backup protection, and a non-biometric fallback. The current recognition pipeline has no liveness detection, so a photo/video replay may fool it.

## Security finding

The downloaded application directory includes SMTP credentials in `config.json`, along with a sample student's face photos, face embeddings, attendance database, logs, and a tunnel executable. The credential is exposed in a local project file, so rotate/revoke that SMTP app password immediately and issue a new one only after deployment. Do not publish or upload those data files. The prepared deployment copy excludes them.
