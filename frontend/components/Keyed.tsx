"use client";

import { Fragment, type ReactNode } from "react";
import { useSession } from "./Providers";

/** Remounts the screen when the store changes: stock, approvers and tills are per store. */
export function Keyed({ children }: { children: ReactNode }) {
  const { store } = useSession();
  return <Fragment key={store}>{children}</Fragment>;
}
