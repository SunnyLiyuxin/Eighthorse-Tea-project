// 八马茶语 API 封装层
// 所有后端调用集中在此，前端通过 BAMA_API.xxx() 调用
const BAMA_API=(function(){
  // BASE 自适应：
  //   - 页面由 nginx / 任意 http(s) 服务时，走同源（""），由网关反代 /api 到后端，
  //     不写死 localhost:8000 否则浏览器会去访客本机找后端 → 跨域 + 连不上。
  //   - 本地直接双击打开 HTML（file://）联调后端时，无同源可用，回退到 localhost:8000。
  const BASE=(typeof window!=="undefined"&&window.location&&window.location.protocol&&window.location.protocol.startsWith("http"))?"":"http://localhost:8000";

  // 茶名→tea_id 映射（仅来源于后端 /api/teas，无任何兜底）
  let TEA_ID_MAP={};

  // GIFT_SCENES value → 后端 recipient 中文 label
  const GIFT_TO_RECIPIENT={
    "self":"自己喝",
    "elder":"送长辈",
    "colleague":"送同事",
    "friend":"送朋友",
    "business":"商务送礼"
  };

  async function request(method, path, body){
    const url=BASE+path;
    const opts={
      method,
      headers:{"Content-Type":"application/json"},
      signal:AbortSignal.timeout(310000) // 310s 超时，适配生图
    };
    if(body)opts.body=JSON.stringify(body);
    let res;
    try{
      res=await fetch(url, opts);
    }catch(e){
      throw new Error("网络请求失败："+e.message+(BASE?"（请确认后端已启动在 "+BASE+"）":"（请确认网关已反代 /api 到后端）"));
    }
    let json;
    try{
      json=await res.json();
    }catch(e){
      throw new Error("响应解析失败：HTTP "+res.status);
    }
    if(!res.ok||!json.success){
      const msg=json.error&&json.error.message?("后端错误["+json.error.code+"]："+json.error.message):("HTTP "+res.status);
      throw new Error(msg);
    }
    // 后端未开放能力返回 success:true + meta.fallback:true + data.message。
    // 这里统一拦截：fallback 时抛带 message 的 Error，让调用方走 .catch 展示友好提示，
    // 而不是去取 data.image_url / data.outputs.* 这些不存在的字段渲染空内容。
    const meta=json.meta||{};
    if(meta.fallback){
      const data=json.data||{};
      const reason=meta.fallback_reason?(" ["+meta.fallback_reason+"]"):"";
      const msg=(data.title?data.title+"：" :"")+(data.message||"该能力 Demo 阶段暂未开放")+reason;
      const err=new Error(msg);
      err.fallback=true;
      err.fallbackData=data;
      throw err;
    }
    return json;
  }

  // 初始化：从后端获取茶品列表建立映射（失败即抛错，不兜底）
  async function init(){
    const r=await request("GET","/api/teas");
    if(r.data&&Array.isArray(r.data)){
      r.data.forEach(t=>{
        if(t.id&&t.name)TEA_ID_MAP[t.name]=t.id;
      });
    }
    console.log("[BAMA_API] 茶品映射已加载:", TEA_ID_MAP);
  }

  function getTeaId(teaName){
    const id=TEA_ID_MAP[teaName];
    if(!id){
      throw new Error("未在 /api/teas 找到茶品「"+teaName+"」的映射，拒绝兜底");
    }
    return id;
  }

  function giftToRecipient(giftValue){
    return GIFT_TO_RECIPIENT[giftValue]||"";
  }

  // 1. 获取茶品列表
  async function getTeas(){
    return request("GET","/api/teas");
  }

  // 2. 国内文案生成
  async function domesticExpression(teaName, sel){
    const teaId=getTeaId(teaName);
    const body={
      audience:{
        knowledge_level: sel.targetConsumer==="入门"?"beginner":(sel.targetConsumer==="专业"?"expert":"intermediate"),
        scenario: "store_sales",
        psychology: ""
      },
      style: "store_sales",
      tone: sel.tone||undefined,
      length: sel.length||undefined,
      time_node: sel.timeNode||undefined,
      task_type: sel.taskType||undefined,
      flavor_reference: sel.flavorReference||undefined,
      recipient: giftToRecipient(sel.giftScene)||undefined
    };
    // 清理 undefined
    Object.keys(body).forEach(k=>body[k]===undefined&&delete body[k]);
    return request("POST", `/api/teas/${teaId}/domestic-expression`, body);
  }

  // 3. 海外文案生成
  async function crossCulturalExpression(teaName, sel){
    const teaId=getTeaId(teaName);
    const body={
      target_language: sel.language||"en",
      market: "western",
      audience_reference: "specialty_coffee_lovers",
      audience_level: sel.targetConsumer==="入门"?"beginner":(sel.targetConsumer==="专业"?"expert":"intermediate"),
      preserve_chinese_terms: true,
      tone: sel.tone||undefined,
      length: sel.length||undefined,
      time_node: sel.timeNode||undefined,
      task_type: sel.taskType||undefined,
      flavor_reference: sel.flavorReference||undefined,
      recipient: giftToRecipient(sel.giftScene)||undefined
    };
    Object.keys(body).forEach(k=>body[k]===undefined&&delete body[k]);
    return request("POST", `/api/teas/${teaId}/cross-cultural-expression`, body);
  }

  // 4. 物料数据生成（第一步）
  // 物料语言由 edition 决定，不透传 sel.language：
  //   国内版 → zh（中文物料 + 中文 copy 印进图）
  //   海外版 → sel.language（用户选的目标语言，默认 en）
  // 修 P0：此前透传 sel.language，而 sel.language 默认 "en"，国内版误发 en →
  //   后端取跨文化英文物料 asset_*_en + 把英文 copy 印进海报图。
  async function marketingAsset(teaName, sel, routeId, edition){
    const teaId=getTeaId(teaName);
    const language=edition==="overseas"?(sel.language||"en"):"zh";
    const body={
      route_id: routeId||("demo_"+teaId),
      asset_type: "poster",
      platform: sel.platform||undefined,
      language,
      style: sel.style||undefined,
      content_theme: sel.content?(sel.content.replace(/-/g,"_")):undefined
    };
    Object.keys(body).forEach(k=>body[k]===undefined&&delete body[k]);
    return request("POST", `/api/teas/${teaId}/marketing-asset`, body);
  }

  // 5. 真实生图（第二步）
  // 物料语言由 edition 决定（同 marketingAsset）：国内版 zh / 海外版 sel.language。
  // 后端按 tea_id + language 从 seed asset 取 copy（headline/subheadline/body）印进图——
  // 国内版必须传 zh，否则会取英文 copy 印进中文海报图（P0 修复点）。
  async function imageGenerate(prompt, teaName, sel, routeId, edition){
    const teaId=getTeaId(teaName);
    const language=edition==="overseas"?(sel.language||"en"):"zh";
    // 物料风格（年轻/商务/国风）→ 生图 style（fresh/business/guofeng）。
    // 三者一一对应：国风不再被降级成 fresh（避免"国风海报"出图却是清新风光照）。
    // 后端 _STYLE_FRAGMENTS 现已含 guofeng；未知值走 fresh 兜底（生图不白屏）。
    const styleMap={"年轻":"fresh","商务":"business","国风":"guofeng"};
    const style=styleMap[sel.style]||"fresh";
    const body={
      prompt: prompt,
      size: "1K",
      style,
      scene: "closeup",
      tea_id: teaId,
      language,
      route_id: routeId||("demo_"+teaId)
    };
    return request("POST", "/api/image/generate", body);
  }

  // 6. 视频生成（Demo 阶段不开放，后端 P2 占位接口恒返回 fallback；
  //    前端在确认生成视频时直接调它，不经 marketingAsset / imageGenerate，
  //    由 request 层统一拦截 meta.fallback 抛带 message 的 Error 展示友好提示）
  async function videoAsset(teaName){
    const teaId=getTeaId(teaName);
    return request("POST", `/api/teas/${teaId}/video-asset`);
  }

  // 7. 工作台自由提问（POST /api/chat）
  // 文案 / 物料工作台的自由输入框统一走本入口：先经后端「意义评判」LLM，
  // 无意义输入（如「？」）被拒（fallback 友好提示）；有意义输入把 text 作为
  // directive 透传到 mode 对应生成链路，真正影响生成。
  //   mode="domestic"|"overseas" → 复用文案 hint，响应 shape 同 domestic/cross-cultural。
  //   mode="material" → 复用物料字段，响应 shape 同 marketing-asset（含 image_prompt）。
  // opts={mode, text, routeId?, edition?}。fallback 由 request 层统一拦截抛 Error。
  // edition 用于物料语言判定：国内版 zh / 海外版 sel.language（避免 sel.language 默认 en 串进国内链）。
  async function chat(teaName, sel, opts){
    const teaId=getTeaId(teaName);
    const mode=opts&&opts.mode;
    const text=((opts&&opts.text)||"").trim();
    const body={tea_id:teaId, mode, text};
    if(mode==="material"){
      body.route_id=opts.routeId||("demo_"+teaId);
      body.asset_type="poster";
      if(sel.platform)body.platform=sel.platform;
      // 物料语言由 edition 决定（国内 zh / 海外 sel.language），与 marketingAsset / imageGenerate 一致
      body.language=(opts.edition==="overseas")?(sel.language||"en"):"zh";
      if(sel.style)body.style=sel.style;
      if(sel.content)body.content_theme=sel.content.replace(/-/g,"_");
    }else{
      body.audience={
        knowledge_level: sel.targetConsumer==="入门"?"beginner":(sel.targetConsumer==="专业"?"expert":"intermediate"),
        scenario: "store_sales",
        psychology: ""
      };
      if(sel.tone)body.tone=sel.tone;
      if(sel.length)body.length=sel.length;
      if(sel.timeNode)body.time_node=sel.timeNode;
      if(sel.taskType)body.task_type=sel.taskType;
      if(sel.flavorReference)body.flavor_reference=sel.flavorReference;
      const rec=giftToRecipient(sel.giftScene);
      if(rec)body.recipient=rec;
      if(mode==="overseas"){
        body.target_language=sel.language||"en";
        body.market="western";
        body.audience_reference="specialty_coffee_lovers";
        body.audience_level=sel.targetConsumer==="入门"?"beginner":(sel.targetConsumer==="专业"?"expert":"intermediate");
        body.preserve_chinese_terms=true;
      }
    }
    return request("POST", "/api/chat", body);
  }

  // 7. 追溯链
  async function getTrace(outputId){
    return request("GET", `/api/trace/${outputId}`);
  }

  // 追溯节点 id → tea_id（仅知识层 / 风味层节点 id 可解析）：
  //   knowledge_szz_tgy_nx / flavor_szz_tgy_nx → BAMA_SZZ_TGY_NX
  // 三茶 abbr 与 tea_id 一致（已验证）。表达层（expr_*）/物料层（asset_*）
  // 节点 id 不走此解析——那两层无 GET 路由，前端不展开。
  function nodeToTeaId(nodeKey){
    const m=String(nodeKey||"").match(/^(?:knowledge|flavor)_(.+)$/);
    return m?("BAMA_"+m[1].toUpperCase()):null;
  }

  // 8. 追溯节点详情：知识层 / 风味层（复用已有 GET，不新增后端接口）
  async function getKnowledgeByNode(nodeKey){
    const teaId=nodeToTeaId(nodeKey);
    if(!teaId) return Promise.reject(new Error("无法从节点解析茶品 id："+nodeKey));
    return request("GET", `/api/teas/${teaId}/knowledge`);
  }
  async function getFlavorByNode(nodeKey){
    const teaId=nodeToTeaId(nodeKey);
    if(!teaId) return Promise.reject(new Error("无法从节点解析茶品 id："+nodeKey));
    return request("GET", `/api/teas/${teaId}/flavor-profile`);
  }

  return {
    init, getTeaId, giftToRecipient,
    getTeas, domesticExpression, crossCulturalExpression,
    marketingAsset, imageGenerate, videoAsset, getTrace, chat,
    nodeToTeaId, getKnowledgeByNode, getFlavorByNode
  };
})();

// 启动时自动初始化
if(typeof window!=="undefined"){
  window.addEventListener("DOMContentLoaded",()=>BAMA_API.init());
}
