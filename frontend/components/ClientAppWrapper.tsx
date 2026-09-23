'use client';

import React from 'react';
import { useTradingWebSocket } from '@/hooks/useTradingWebSocket';
import { useTradingStore } from '@/store/useTradingStore';
import { StitchHeader } from './navigation/StitchHeader';
import { StitchSidebar } from './navigation/StitchSidebar';

export const ClientAppWrapper: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  // Establish real-time WebSocket connection to backend
  useTradingWebSocket();


  return (
    <div className="bg-surface font-body-md text-body-md text-on-surface min-h-screen select-none">
      <StitchHeader />
      <StitchSidebar />
      <div className="pl-60 pt-20">
        <main className="w-full bg-surface min-h-screen">
          {children}
        </main>
      </div>
    </div>
  );
};
