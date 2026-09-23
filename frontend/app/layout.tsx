import type { Metadata } from 'next';
import './globals.css';
import { ClientAppWrapper } from '@/components/ClientAppWrapper';

export const metadata: Metadata = {
  title: 'TRDENG | Quant Execution Trading Terminal',
  description: 'High-Throughput Institutional Quant Execution Engine Dashboard & Real-Time Telemetry',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className="bg-surface font-body-md text-on-surface antialiased">
        <ClientAppWrapper>{children}</ClientAppWrapper>
      </body>
    </html>
  );
}
