import type { Metadata } from 'next';
import { Geist } from 'next/font/google';
import './globals.css';

const geist = Geist({
  variable: '--font-geist-sans',
  subsets: ['latin'],
});

export const metadata: Metadata = {
  title: 'MOPS | 한울 주변 대량 해파리 군집 감시',
  description: '공개데이터 기반 해파리 관측·조건부 이동·감시격자 근거 조회 대시보드',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body className={`${geist.variable} antialiased`}>{children}</body>
    </html>
  );
}
