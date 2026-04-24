import type { Metadata } from "next";
import type { ReactNode } from "react";
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
        <div className="app-shell">
          <header className="topbar">
            <div>
              <p className="eyebrow">车型口碑分析演示</p>
              <h1>车主口碑洞察工作台</h1>
            </div>
            <p className="topbar-copy">
              输入车型名称，确认平台车系，在线查看采集、摘要、词云、一页纸和问答结果。
            </p>
          </header>
          {children}
        </div>
      </body>
    </html>
  );
}
