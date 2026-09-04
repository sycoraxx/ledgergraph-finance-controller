import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Finance Controller — Reconcile, review, approve',
  description: 'Explain payouts, review exceptions, and approve balanced journals with deterministic financial controls.',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
