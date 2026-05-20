import type { Metadata } from "next"
import { Inter, JetBrains_Mono } from "next/font/google"
import "./globals.css"

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" })
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono", display: "swap" })

export const metadata: Metadata = {
  title: "Mesh — Your AI agents, finally working together",
  description:
    "Connect your Claude Code instances. Let them talk to each other, coordinate work, share context — in real time, from anywhere. Free to start.",
  metadataBase: new URL(process.env.NEXT_PUBLIC_APP_URL || "http://localhost:3000"),
  openGraph: {
    title: "Mesh",
    description: "Your AI agents, finally working together.",
    images: ["/og-image.png"],
  },
  twitter: { card: "summary_large_image" },
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${mono.variable}`}>
      <body className="min-h-screen bg-bg text-text">{children}</body>
    </html>
  )
}
