import { redirect } from "next/navigation";
import { withBasePath } from "@/lib/paths";

export default function HomePage() {
  redirect(withBasePath("/passphrase"));
}
