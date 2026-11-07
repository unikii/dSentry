import { createContext } from "react";

export interface ServerEnvs {
  run_mode: "private" | "public";
  metrics_data_lifespan: string;
  global_push_interval: number;
  global_node_per_user: number;
  global_device_per_node: number;
  global_raw_push_base: string;
  global_raw_push_freq: number;
  global_raw_push_plain: boolean;
  smtp_enabled: boolean;
  login_notify_banner: string | null;
}

export interface EnvsContextValue {
  envs: ServerEnvs | null;
  loading: boolean;
  refresh: () => Promise<ServerEnvs | null>;
}

export const EnvsContext = createContext<EnvsContextValue>({
  envs: null,
  loading: true,
  refresh: async () => null,
});
