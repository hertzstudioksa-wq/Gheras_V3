import { useEffect } from "react";

const SITE = "غِراس";

/** Sets the browser tab title ("<page> | غِراس"); the home page passes nothing. */
export function usePageTitle(title) {
  useEffect(() => {
    document.title = title ? `${title} | ${SITE}` : `${SITE} — قصة كرتون بطلها طفلك`;
  }, [title]);
}
