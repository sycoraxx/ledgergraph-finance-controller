import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Finance Controller — Settlement Control Room',
  description: 'Evidence-first reconciliation with deterministic money logic and gated AI assistance.',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
