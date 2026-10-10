const path=require('node:path'),{createRequire}=require('node:module'),{pathToFileURL}=require('node:url');
const project=path.resolve(__dirname,'../../..'),req=createRequire(path.join(project,'src/frontend/package.json'));
(async()=>{
 const {createServer}=await import(pathToFileURL(req.resolve('vite')).href);
 const {default:vue}=await import(pathToFileURL(req.resolve('@vitejs/plugin-vue')).href);
 const aliases=['vue','element-plus','@element-plus/icons-vue','@fontsource-variable/noto-sans-sc','@fontsource-variable/noto-serif-sc'].map(name=>({find:new RegExp('^'+name+'$'),replacement:req.resolve(name)}));
 aliases.push({find:'@',replacement:path.join(project,'src/frontend/src')},{find:'@icon-park/vue-next',replacement:path.join(project,'src/frontend/node_modules/@icon-park/vue-next')});
 const server=await createServer({configFile:false,root:__dirname,plugins:[vue()],resolve:{alias:aliases},cacheDir:path.join(project,'qa/tube_revision_design_20260929/vite-cache'),server:{host:'127.0.0.1',port:8104,strictPort:true,fs:{allow:[project]}}});
 await server.listen();console.log('管材设计原型 http://127.0.0.1:8104/ — 仅示例，未连接业务API');
})().catch(e=>{console.error(e.message);process.exitCode=1});
