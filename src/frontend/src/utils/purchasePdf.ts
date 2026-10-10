import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

GlobalWorkerOptions.workerSrc = workerUrl

// 包含旧归档 PDF 使用的中文字符映射和标准字体，资源由 Vite 随应用打包。
const assets = import.meta.glob<string>('/node_modules/pdfjs-dist/{cmaps,standard_fonts,wasm}/*', {
  query: '?url&no-inline', import: 'default', eager: true,
})
class LocalPdfDataFactory {
  async fetch({ kind, filename }: { kind: string; filename: string }): Promise<Uint8Array> {
    const folders: Record<string, string> = { cMapUrl: 'cmaps', standardFontDataUrl: 'standard_fonts', wasmUrl: 'wasm' }
    const url = assets[`/node_modules/pdfjs-dist/${folders[kind]}/${filename}`]
    if (!url) throw new Error('PDF 所需资源不存在。')
    const response = await fetch(url)
    if (!response.ok) throw new Error('PDF 所需资源加载失败。')
    return new Uint8Array(await response.arrayBuffer())
  }
}

export function loadPurchasePdf(data: Uint8Array) {
  return getDocument({ data, stopAtErrors: true, useWorkerFetch: false, BinaryDataFactory: LocalPdfDataFactory })
}
