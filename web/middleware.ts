export { default } from "next-auth/middleware";

export const config = {
  matcher: ["/settings", "/profile", "/evaluate", "/organizations/:path*"],
};
