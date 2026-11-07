import { useContext } from "react";
import { LangContext } from "@/context/lang-context";

export function useLanguage() {
  return useContext(LangContext);
}
