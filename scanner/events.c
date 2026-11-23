/* Local-only build: omit the optional Linux D-Bus status notification channel. */
int SendScanEvent(char *uri, int event) { (void)uri; (void)event; return 1; }
