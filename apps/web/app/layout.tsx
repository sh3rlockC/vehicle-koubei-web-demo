import type { Metadata } from "next";
import type { ReactNode } from "react";
import { AppChrome } from "./components/app-chrome";
import "./globals.css";

export const metadata: Metadata = {
  title: "车型口碑分析演示",
  description: "车型口碑采集、摘要、词云、一页纸和问答演示工具。",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>
        <AppChrome>{children}</AppChrome>
      </body>
    </html>
  );
}
