import "next-auth";
import "next-auth/jwt";

declare module "next-auth" {
  interface User {
    hotkey: string;
  }
  interface Session {
    user: {
      name?: string | null;
      email?: string | null;
      image?: string | null;
      hotkey: string;
    };
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    hotkey?: string;
  }
}
