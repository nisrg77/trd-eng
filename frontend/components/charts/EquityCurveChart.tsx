'use client';

import React from 'react';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { useTradingStore } from '@/store/useTradingStore';

export const EquityCurveChart: React.FC = () => {
  const equityCurve = useTradingStore((state) => state.equityCurve);

  return (
    <div className="w-full h-full min-h-[220px] bg-[#090d16] border border-slate-800 rounded-xl p-3 flex flex-col">
      <div className="flex items-center justify-between pb-2 border-b border-slate-800 mb-2">
        <span className="text-xs font-bold text-slate-300 uppercase tracking-wider">Portfolio Equity Curve</span>
        <span className="text-xs font-mono text-emerald-400 font-semibold">10x Leverage Margin</span>
      </div>

      <div className="w-full flex-1 min-h-[160px]">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={equityCurve} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
            <defs>
              <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#10b981" stopOpacity={0.4} />
                <stop offset="95%" stopColor="#10b981" stopOpacity={0.0} />
              </linearGradient>
            </defs>
            <XAxis dataKey="time" stroke="#475569" fontSize={10} tickLine={false} />
            <YAxis stroke="#475569" fontSize={10} tickLine={false} domain={['auto', 'auto']} />
            <Tooltip
              contentStyle={{ background: '#090d16', borderColor: '#334155', borderRadius: '8px', fontSize: '12px' }}
              labelStyle={{ color: '#94a3b8' }}
            />
            <Area
              type="monotone"
              dataKey="equity"
              stroke="#10b981"
              strokeWidth={2}
              fillOpacity={1}
              fill="url(#equityGradient)"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};
