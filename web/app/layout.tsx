import type { Metadata } from 'next';
import './globals.css';

const siteUrl = process.env.NEXT_PUBLIC_SITE_URL || 'http://localhost:3000';

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: 'Finance Controller — Reconcile, review, approve',
  description: 'Explain payouts, review exceptions, and approve balanced journals with deterministic financial controls.',
  openGraph: {
    title: 'Finance Controller',
    description: 'Reconcile. Review. Approve.',
    images: [{ url: '/og.png', width: 1732, height: 909, alt: 'Finance Controller — Reconcile. Review. Approve.' }],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Finance Controller',
    description: 'Reconcile. Review. Approve.',
    images: ['/og.png'],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
