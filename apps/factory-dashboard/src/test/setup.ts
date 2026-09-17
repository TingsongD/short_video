import "@testing-library/jest-dom/vitest";

// Node 26 exposes an unavailable global localStorage without a file. Supply
// the browser storage boundary explicitly; no Node profile file is used.
const items = new Map<string,string>();
Object.defineProperty(window,"localStorage",{configurable:true,value:{
  getItem:(key:string)=>items.get(key)??null,
  setItem:(key:string,value:string)=>items.set(key,String(value)),
  removeItem:(key:string)=>items.delete(key),clear:()=>items.clear(),
  key:(index:number)=>Array.from(items.keys())[index]??null,
  get length(){return items.size;},
}});
