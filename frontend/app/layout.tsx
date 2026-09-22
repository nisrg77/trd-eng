import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'TEDENG | High-Performance FinTech Algorithmic Trading Dashboard',
  description: 'Real-time ML Algorithmic Trading Engine Dashboard with TradingView Lightweight Charts & WebSockets',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className="bg-[#05080f] text-slate-100 antialiased selection:bg-cyan-500/30">
        {children}
      </body>
    </html>
  );
}
