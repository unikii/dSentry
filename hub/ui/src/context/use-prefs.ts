import { useContext } from "react";
import { PrefsContext } from "@/context/prefs-context";

export function usePrefs() {
  return useContext(PrefsContext);
}
