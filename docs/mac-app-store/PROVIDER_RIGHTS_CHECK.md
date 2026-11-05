# Provider-service rights checkpoint

Checked: 2026-11-06, by fetching the public primary pages. This is an engineering release-readiness check, not a determination of legal liability. No account credentials, private conversation or attachment was submitted to obtain it.

| Source | Observed requirement | Application to this candidate |
|---|---|---|
| [OpenAI Terms of Use](https://openai.com/policies/terms-of-use/), effective January 1, 2026, Using our Services | Consumer terms restrict automated/programmatic extraction of output. Business/API terms are separate. | A consumer login does not establish permission for TWOS's automated webpage extraction/relay. No specific permission evidence has been supplied. |
| [Anthropic Consumer Terms](https://www.anthropic.com/legal/consumer-terms), effective October 8, 2025, §3(4), §3(7) | Scraping/harvesting is restricted; automated access requires an API key or another explicit allowance. | Claude webpage sign-in is not API authorization or a demonstrated exception. No specific allowance has been verified. |
| [DeepSeek Terms of Use](https://cdn.deepseek.com/policies/en-US/deepseek-terms-of-use.html), updated March 27, 2026, §§3.1, 3.5(3), 3.6(4) | Unspecified rights are reserved; the restrictions address automatic capture/copying and unauthorized transfer of the service. | We cannot infer a redistribution/automated-relay license from successful normal webpage interaction. Applicability and any exception remain to be confirmed by the provider. |
| [Apple App Review Guidelines](https://developer.apple.com/app-store/review/guidelines/), §5.2.2 | Access/display of third-party services must be specifically permitted under their terms; Apple can request authorization. | The Store permission gate is unresolved. No App Store submission or assertion of provider endorsement is appropriate on this evidence. |

Technical Store gaps remain separate: sandbox-compatible selected-folder persistence, external execution/self-contained installation, helper/container lifecycle and actual App Store Connect identity/provisioning/reviewer access.

The Owner previously reported no known permission applications. The next Store decision requires either verifiable provider permission for the precise webpage relay use or explicit approval of a permitted alternative integration and any product/billing consequences. Do not silently remove core functionality, change to paid APIs, accept terms, send provider messages or buy accounts. Ordinary engineering/source distribution authorization does not itself supply third-party rights.

No new model tasks were started for this check. Existing approved DMG engineering, Nyra and public English-site work continue independently; this document does not mark Store preparation complete.
