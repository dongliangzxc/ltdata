const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')

const source = fs.readFileSync(path.join(__dirname, 'CreateModelModal.tsx'), 'utf8')

for (const prop of ['productImage', 'productName', 'productBrand', 'productUrl']) {
  assert.match(source, new RegExp(`${prop}\\?: string \\| null`), `modal should accept ${prop}`)
}
assert.match(source, /hasProductPreview \? 960 : 720/, 'modal should widen when product preview is shown')
assert.match(source, /import HoverZoomImage from '.\/HoverZoomImage'/, 'modal should reuse hover zoom image')
assert.match(source, /<HoverZoomImage src=\{productImage/, 'modal should render hover zoom product image')
assert.match(source, /悬停图片可局部放大，点击可查看大图/, 'product preview should explain hover zoom and click preview')

assert.match(source, /新窗口打开原图/, 'product preview should allow opening the original image in a new tab')
assert.match(source, /打开商品链接/, 'product preview should expose item link')
assert.match(source, /maskClosable=\{false\}/, 'modal should not close when clicking the mask')


console.log('CreateModelModal product preview assertions passed')
