# TWOS 1.0.9 / 101.57 — Website address repair candidate

The Owner reported that selecting **Website…**, entering a private-network HTTP address and clicking **Open** silently closed the address dialog on either side. In the installed 1.0.8 baseline, input validation accepted HTTP only on the local computer. The rejected address was handled like Cancel, before any WebKit navigation.

The development fix keeps the address sheet open with a specific reason when an address is rejected. It accepts HTTPS, local-computer HTTP, and explicit RFC 1918 IPv4 HTTP addresses (10.x.x.x, 172.16–31.x.x, 192.168.x.x). Unencrypted HTTP navigation is limited to the exact selected host and port. No model task, cross-pane send, site operation, credential transfer, or global security exception is implied by opening a page.

Choose **Website…** on the intended side → enter the complete address including `http://` or `https://` and the port if needed → **Open**. Check the displayed origin and loaded page. Cancel preserves the original pane. An invalid address stays editable. A network failure shows a retry notice; successful loading clears that notice. An explicit new address takes precedence over an older saved location on that host.

Addresses containing credentials, query parameters or fragments remain unsupported in the initial address sheet; the specific reason is displayed. Open the site without those parts and navigate within it. Public HTTP and non-HTTP(S) schemes remain blocked. This does not add automated handoff to arbitrary websites.

Status: development implementation and limited isolated GUI checks; final packaged verification and the matching complete gate are still pending. The public download remains 1.0.8 until a verified successor is published. Do not replace an installed app with an engineering candidate. No new Owner acceptance is asserted.
