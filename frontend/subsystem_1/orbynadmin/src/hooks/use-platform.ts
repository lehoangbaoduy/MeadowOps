import * as React from "react";

/**
 * Detects whether the current device is an Apple platform (Mac / iOS) so
 * keyboard hints can show the right modifier — ⌘ on Mac, Ctrl on Windows/Linux.
 * Defaults to `true` on the server and the first client render to avoid a
 * hydration mismatch, then corrects to the real value after mount.
 */
export function useIsMac() {
  const [isMac, setIsMac] = React.useState(true);
  React.useEffect(() => {
    const nav = navigator as Navigator & {
      userAgentData?: { platform?: string };
    };
    const platform =
      nav.userAgentData?.platform || nav.platform || nav.userAgent || "";
    setIsMac(/mac|iphone|ipad|ipod/i.test(platform));
  }, []);
  return isMac;
}
