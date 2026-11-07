import { createContext } from "react";
import type { UserResponse } from "@/client";

export interface AuthContextValue {
  token: string | null;
  user: UserResponse | null;
  ready: boolean;
  signIn: (token: string, user: UserResponse) => void;
  signOut: () => void;
  refreshUser: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue>({
  token: null,
  user: null,
  ready: false,
  signIn: () => {},
  signOut: () => {},
  refreshUser: async () => {},
});
