import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import test from 'node:test';

const escape=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function setup(){
  const copied=[],messages=[];
  const context={window:{},esc:escape,ManuscriptReader:{build:value=>({html:'<p>'+escape(value)+'</p>'})},navigator:{clipboard:{writeText:async value=>{copied.push(value);}}},location:{hash:'#/campaigns/example/results'},toast:message=>messages.push(message)};
  runInNewContext(readFileSync(new URL('../static/video-script.js',import.meta.url),'utf8'),context);
  return {ui:context.window.VideoScript,copied,messages,context};
}
const fixture=`配图讲解 · 计划 60 秒 · 画幅 9:16

#### 配音稿

旧的重复配音，显示和复制应以当前镜头为准。

#### 镜头脚本

##### 镜头 01 · 0–6 秒

**画面：** 岩石上的叶片。

**屏幕文字：** 石缝里也有生命

**口播：** 第一镜实际口播。

**剪辑：** 缓慢推进。

**使用素材：** M01

##### 镜头 02 · 6–12 秒

**画面：** 书页。

**屏幕文字：** 翻开这本书

**口播：** 第二镜实际口播，完整结尾。

**剪辑：** 淡出。

**使用素材：** M02

#### 准备素材

##### M01 · 岩石

素材特有说明：现场拍摄。

#### 发布文案

发布特有文案：一起认识身边的植物。
`;
function fakeRoot(key){
  const content={innerHTML:''},focus={count:0};
  const root={isConnected:true,dataset:{videoScript:key},querySelector(selector){
    if(selector==='.video-script-content')return content;
    if(selector==='[role="tab"][aria-selected="true"]')return {focus(){focus.count++;}};
    const name=selector.match(/^\[data-section="(.+)"\]$/)?.[1];return name?tab(name):null;
  }};
  const tab=section=>({isConnected:true,dataset:{section},closest:()=>root});
  const button={isConnected:true,disabled:false,closest:()=>root};
  return {root,content,focus,tab,button};
}

const imagePrompt='面向 11—14 岁读者；风格为纸艺；画幅 9:16；以本镜已核对的书中叶片照片作为参考，生成岩石旁的叶片。';
const videoPrompt='面向 11—14 岁读者；风格为纸艺；画幅 9:16；以本镜已确认的静帧为输入，缓慢推进 6 秒，保持叶片形状。';
const fivePartFixture=fixture+'\n#### 生成提示词\n\n按镜头复制。先准备所列参考图并确认静帧，再制作动态片段；字幕在剪辑时添加。\n\n##### 镜头 01 · 0–6 秒\n\n**生图提示词：** '+imagePrompt+'\n\n**生视频提示词：** '+videoPrompt+'\n\n##### 镜头 02 · 6–12 秒\n\n**生图提示词：** 第二镜完整生图上下文。\n\n**生视频提示词：** 第二镜完整生视频上下文。\n';


test('stage one shows only the current narration with character count and planned duration',async()=>{
  const {ui,copied}=setup(),source='# 认识植物\n\n'+fixture;
  const rendered=ui.render(source,'current');
  assert.match(rendered,/认识植物/);assert.match(rendered,/口播稿 · \d+ 字（不含标点） · 计划 60 秒/);
  assert.match(rendered,/第一镜实际口播/);assert.match(rendered,/第二镜实际口播/);
  assert.doesNotMatch(rendered,/role="tab"|镜头脚本|准备素材|发布文案|生成提示词|素材特有说明|发布特有文案|画面：|旧的重复配音/);
  const view=fakeRoot('current');await ui.copy(view.button);
  assert.equal(copied[0],'第一镜实际口播。\n\n第二镜实际口播，完整结尾。');
  assert.equal(ui.narration(source),copied[0]);
});

test('historical five-section manuscripts show and copy narration only without deleting their production content',async()=>{
  const {ui,copied}=setup(),rendered=ui.render(fivePartFixture,'history');
  assert.doesNotMatch(rendered,/role="tab"|生成提示词|旧版提示词|纸艺|素材特有说明|发布特有文案/);
  const view=fakeRoot('history');await ui.copy(view.button);
  assert.doesNotMatch(copied[0],/纸艺|镜头|准备素材|发布文案/);
  assert.equal(ui.parse(fivePartFixture).parts.length,5);
  assert.match(ui.parse(fivePartFixture).parts.find(x=>x.name==='生成提示词').raw,/纸艺/);
});

test('unknown manuscripts fall back intact and headings inside code remain in their original section',()=>{
  const {ui}=setup();
  for(const unknown of [fixture.replace('#### 发布文案','#### 未知部分'),fixture.replace('#### 发布文案','#### 配音稿'),fixture.replace(/#### 发布文案[\s\S]*/,''),'【开场 0—5秒】\n画面：岩石\n口播：植物']){
    assert.equal(ui.parse(unknown),null);assert.equal(ui.render(unknown,'unknown'),'');
  }
  const source=fixture+'\n```text\n#### 非章节\n```\n';
  assert.match(ui.parse(source).parts.find(x=>x.name==='发布文案').raw,/#### 非章节/);
});

test('focused edits synchronize both narration copies and retain all non-narration sections',async()=>{
  const {ui,copied}=setup(),voices=ui.prepareOutlineEdit(fivePartFixture);
  assert.equal(voices.length,2);assert.equal(voices[0].text,'第一镜实际口播。');
  const saved=ui.finishOutlineEdit(fivePartFixture,['这是重新写的开头。','这是重新写的结尾。']);
  assert.ok(saved);assert.equal((saved.match(/这是重新写的开头。/g)||[]).length,2);
  assert.equal((saved.match(/这是重新写的结尾。/g)||[]).length,2);
  const before=ui.parse(fivePartFixture),after=ui.parse(saved);
  for(const name of ['准备素材','发布文案','生成提示词'])assert.equal(after.parts.find(x=>x.name===name).raw,before.parts.find(x=>x.name===name).raw);
  assert.match(saved,/\*\*画面：\*\* 岩石上的叶片/);assert.match(saved,/\*\*剪辑：\*\* 缓慢推进/);
  ui.render(fivePartFixture,'current');ui.render(saved,'current');await ui.copy(fakeRoot('current').button);
  assert.equal(copied[0],'这是重新写的开头。\n\n这是重新写的结尾。');
});

test('complete manuscript editing keeps the old five parts and rejects ambiguous structures',()=>{
  const {ui}=setup(),edit=ui.prepareEdit(fivePartFixture);
  assert.doesNotMatch(edit.body,/#### 配音稿/);assert.match(edit.body,/#### 生成提示词/);
  const edited=edit.body.replace('第一镜实际口播。','完整编辑器改过的口播。');
  const saved=ui.finishEdit(edited,edit.voiceIndex,edit.sectionCount);
  assert.equal(ui.parse(saved).parts.length,5);assert.equal(ui.prepareEdit(saved).body,edited);
  assert.match(ui.narration(saved),/完整编辑器改过的口播/);
  assert.equal(ui.finishEdit(edited.replace(/\n#### 生成提示词[\s\S]*/,''),edit.voiceIndex,edit.sectionCount),null);
  assert.equal(ui.finishOutlineEdit(fixture,['只有一段']),null);assert.equal(ui.finishOutlineEdit(fixture,['','结尾']),null);
});

test('no planned duration is invented when it is absent from the stored manuscript',()=>{
  const {ui}=setup();assert.doesNotMatch(ui.render(fixture.replace('计划 60 秒','时长待定'),'no-duration'),/计划 \d+ 秒|预计朗读|实测/);
});

test('detached controls do not copy another document',async()=>{
  const {ui,copied}=setup();ui.render(fixture,'current');const view=fakeRoot('current');view.root.isConnected=false;await ui.copy(view.button);assert.equal(copied.length,0);
});
