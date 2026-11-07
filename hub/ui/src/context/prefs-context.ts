import { createContext } from "react";

export type NavSide = "left" | "right";

export interface PrefsContextValue {
  navSide: NavSide;
  navSlim: boolean;
  setNavSide: (side: NavSide) => void;
  setNavSlim: (slim: boolean) => void;
}

export const PrefsContext = createContext<PrefsContextValue>({
  navSide: "right",
  navSlim: false,
  setNavSide: () => {},
  setNavSlim: () => {},
});
