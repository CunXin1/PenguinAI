import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { Navbar } from "@/components/layout/Navbar";

export const metadata: Metadata = {
  title: "PenguinAI - AI Investment Signal Platform",
  description: "Quantitative AI signal recommendations for US equities",
};

/**
 * Applies the saved theme before first paint to avoid a flash of the wrong
 * theme (FOUC). Defaults to dark when nothing is stored.
 */
const themeScript = `(function(){try{var t=localStorage.getItem('theme');if(t==='light'){document.documentElement.classList.remove('dark');}else{document.documentElement.classList.add('dark');}}catch(e){document.documentElement.classList.add('dark');}})();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="min-h-screen antialiased font-sans">
        <Providers>
          <Navbar />
          {children}
        </Providers>
      </body>
    </html>
  );
}
