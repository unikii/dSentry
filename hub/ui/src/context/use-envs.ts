import { useContext } from "react";
import { EnvsContext } from "@/context/envs-context";

export function useEnvs() {
  return useContext(EnvsContext);
}
