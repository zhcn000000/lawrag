import type { NavigateFunction } from "react-router-dom";

let navigateFn: NavigateFunction | null = null;

export function setNavigate(fn: NavigateFunction | null) {
  navigateFn = fn;
}

export function navigate(to: string, options?: { replace?: boolean }) {
  if (navigateFn) {
    navigateFn(to, options);
  } else {
    window.location.href = `${import.meta.env.BASE_URL}${to.replace(/^\//, "")}`;
  }
}
