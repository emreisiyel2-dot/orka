import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ORKA — AI Command Center",
  description: "Multi-agent command center dashboard for orchestrating AI teams",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="bg-base text-zinc-200 font-sans antialiased min-h-screen">
        {children}
      </body>
    </html>
  );
}
