"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { todayVn } from "@/lib/format";

const AsOf = createContext<{ asOf: string; setAsOf: (v: string) => void }>({ asOf: "", setAsOf: () => {} });

export function AsOfProvider({ children }: { children: ReactNode }) {
  const [asOf, setAsOf] = useState("");
  // Ngày phụ thuộc lúc chạy trên trình duyệt: đặt sau hydrate để server và client khớp nhau
  useEffect(() => setAsOf(todayVn()), []);
  return <AsOf.Provider value={{ asOf, setAsOf }}>{children}</AsOf.Provider>;
}

export const useAsOf = () => useContext(AsOf);
