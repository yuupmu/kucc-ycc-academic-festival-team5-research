import fs from 'node:fs/promises';
import path from 'node:path';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';
const base=process.argv[2], preview=process.argv[3];
const get=async f=>JSON.parse(await fs.readFile(path.join(base,f),'utf8'));
const [scores,items,cases,questions,versions,changes,hist,histQuestions,scope]=await Promise.all([
 'research/scores.json','research/items.json','sample.json','research/questions.json','research/snapshots.json',
 'research/transitions.json','research/historical.json','research/historical-qa.json','research/historical-scope.json'].map(get));
const wb=Workbook.create();
const labels=Object.fromEntries(scores.map(d=>[d.arm,d.label]));
const typeMap=Object.fromEntries(cases.map(c=>[c.kind,c.type]));
const casesBy=Object.fromEntries(cases.map(c=>[c.id,c]));
const stageNames=Array.from(new Set(items.map(i=>i.stage)));
const types=Object.keys(typeMap);
const noun={clock:'정정 기산점',duration:'정정 기간',end:'정정 끝점 포함',deadline:'일반 마감 포함',late:'마감 뒤 정정 허용',start:'시작 정각 거부',after:'시작 뒤 거부',expired:'두 기한 모두 만료',ordinary_before:'일반 마감 전 허용',ordinary_late:'일반 마감 지남',ordinary_started:'이용 시작 시 일반 마감',overlap_allowed:'정정 만료·일반 취소 가능',both_allowed:'두 경로 모두 가능',inputs:'입력 유효 범위',unit:'입력 단위',rank:'복수 태그 우선순위',unknown:'미등록 혼합 처리',empty:'담당 태그 없을 때',ab:'account·billing',ap:'account·privacy',bp:'billing·privacy',empty_list:'빈 목록',unknown_only:'미등록만 있음',invariant:'순서·중복 불변',one_known:'담당 한 종류',three_known:'세 담당 태그',clarify:'구체화 요청',unset:'정책 미정'};
const task=t=>t==='reservation'?'예약 취소':'문의 배정';
const ids=a=>a.join(', ');
const facts=a=>a.map(k=>noun[k]||k).join(', ');
const mapped=o=>Object.entries(o).map(([k,n])=>k+' '+n).join(', ');
const show=x=>x===null||x===undefined?'':typeof x==='boolean'?(x?'허용':'거부'):String(x);
const asCode=x=>typeof x==='string'&&x.startsWith('=')?"'"+x:x;
const tagList=c=>c.task==='reservation'?c.inputs.join(' / '):JSON.stringify(c.inputs);
function col(n){let c='';while(n){n--;c=String.fromCharCode(65+n%26)+c;n=Math.floor(n/26);}return c;}
let seq=0;
function sheet(name,headers,rows,widths,opt={}){
 const sh=wb.worksheets.add(name); sh.showGridLines=false;
 const last=rows.length+1,end=col(headers.length);
 sh.getRange('A1:'+end+last).values=[headers,...rows].map(row=>row.map(v=>asCode(v??null)));
 sh.getRange('A1:'+end+last).format.font={name:'Apple SD Gothic Neo',size:10,color:'#163044'};
 sh.getRange('A1:'+end+last).format.rowHeight=17;
 const tbl=sh.tables.add('A1:'+end+last,true,'StudyTable'+(++seq));tbl.style='TableStyleMedium2';tbl.showFilterButton=true;
 sh.getRange('A1:'+end+'1').format={fill:'#164457',font:{name:'Apple SD Gothic Neo',bold:true,size:10,color:'#FFFFFF'},rowHeight:34,wrapText:true,verticalAlignment:'center'};
 widths.forEach((w,j)=>sh.getRange(col(j+1)+'1:'+col(j+1)+last).format.columnWidth=w);
 sh.freezePanes.freezeRows(1);
 if(opt.wrap){
   for(const j of opt.wrap) sh.getRange(col(j+1)+'2:'+col(j+1)+last).format.wrapText=true;
   for(let i=0;i<rows.length;i++){
     const lines=Math.max(1,...opt.wrap.map(j=>String(rows[i][j]??'').split('\n').reduce((n,x)=>n+Math.max(1,Math.ceil(x.length/(widths[j]*0.60))),0)));
     sh.getRange('A'+(i+2)+':'+end+(i+2)).format.rowHeight=Math.min(300,Math.max(30,lines*12.5+8));
   }
 }
 return sh;
}
const summary=sheet('구조별 결과',['파이프라인','예약 정답 /50','문의 정답 /50','정답 /100','오답','보류','오류','기존 /20','추가 /80','단독 대비 새 정답','단독 대비 잃은 정답','질문 수','회신 묶음','모델 호출','입력 토큰','출력 토큰','총 토큰','모델 응답 초'],
 scores.map(s=>[s.label,s.reservation,s.triage,s.correct,s.wrong,s.defer,s.errors,s.old20,s.new80,s.gained,s.lost,s.questions,s.windows,s.calls,s.prompt_tokens,s.completion_tokens,s.total_tokens,Number(s.seconds.toFixed(2))]),
 [35,14,14,14,8,8,8,12,12,17,17,11,12,12,15,15,15,14]);
for(let i=2;i<=scores.length+1;i++){summary.getRange('D'+i).formulas=[['=SUM(B'+i+':C'+i+')']];summary.getRange('Q'+i).formulas=[['=SUM(O'+i+':P'+i+')']];}
summary.getRange('O2:Q'+(scores.length+1)).format.numberFormat='#,##0';
sheet('유형별 정답',['유형','정책 상황','문항 수',...scores.map(s=>s.label)],types.map(k=>[k,typeMap[k],cases.filter(c=>c.kind===k).length,...scores.map(s=>s.types[k])]),[9,32,12,...scores.map(()=>18)]);
sheet('질문과 답변',['파이프라인','과제','회차','순번','질문 제안자','실제 질문 원문','대리 담당자의 질문별 회신','처음 받은 회신 문구의 주제','관련 유형','회신 묶음으로 근거 충족','관련 문항 중 회차 개선','관련 문항 중 회차 퇴행','회차 개선 유형별 수','회차 퇴행 유형별 수','원기록','회신 출처'],
 questions.map(q=>[labels[q.arm],task(q.task),q.cycle,q.order,q.by,q.question,q.answer,facts(q.fresh),ids(q.kinds),ids(q.sufficient),ids(q.gained),ids(q.lost),mapped(q.gain_types),mapped(q.loss_types),q.source,q.origin]),
 [34,13,8,8,15,82,70,31,23,36,36,36,25,25,58,45],{wrap:[5,6]});
sheet('문항 100개',['문항','과제','유형','정책 상황','입력 (예약은 경과 초 / 시작까지 초)','기준 반환','종전 20문항 ID','충분한 정책 조합 (또는)'],
 cases.map(c=>[c.id,task(c.task),c.kind,c.type,tagList(c),show(c.expected),c.old_id,c.owner_paths.length?c.owner_paths.map(facts).join(' 또는 '):'공개 명세']),[10,14,10,34,56,15,19,75]);
sheet('문항별 실행',['파이프라인','회차','최종 제출','과제','문항','유형','입력','기준 반환','실제 반환','판정','마지막 실행 줄','근거 상태','확보 근거 또는 미확보 대안','관련 회차.질문','놓친 단계','예외','제출 식별 경로'],
 items.map(i=>{const c=casesBy[i.id];return [labels[i.arm],i.cycle,i.final?'최종':'중간',task(i.task),i.id,i.kind,tagList(c),show(c.expected),show(i.actual),i.status,i.line,i.evidence,facts(i.facts),ids(i.question_refs),i.stage,i.error,i.code_source]}),
 [35,8,12,12,9,9,45,14,14,14,14,16,43,29,30,26,65]);
sheet('놓친 단계',['파이프라인',...stageNames],scores.map(s=>[s.label,...stageNames.map(k=>s.diagnosis[k]||0)]),[35,...stageNames.map(()=>24)]);
const armName=k=>k.includes('/')?labels[k.split('/')[0]]+' '+k.split('/')[1]+'회':labels[k];
sheet('구조 전후 변화',['이전','이후','새 정답','잃은 정답','순변화','새 정답 유형별 수','잃은 정답 유형별 수','새 정답 문항','잃은 정답 문항','반환·상태가 바뀐 문항'],
 changes.map(v=>[armName(v.before),armName(v.after),v.gained.length,v.lost.length,v.gained.length-v.lost.length,mapped(v.gain_types),mapped(v.loss_types),ids(v.gained),ids(v.lost),ids(v.changed)]),[38,38,12,13,12,48,48,53,53,64]);
sheet('회차와 비용',['파이프라인','과제','회차','최종 여부','정답 /50','오답','보류','오류','모델 호출 누계','입력 토큰 누계','출력 토큰 누계','상태','코드 SHA-256','제출 원기록','당시까지의 실제 회신 묶음'],
 versions.map(v=>[labels[v.arm],task(v.task),v.cycle,v.final?'최종':'중간',v.counts['정답']||0,v.counts['오답']||0,v.counts['보류']||0,(v.counts['실행 오류']||0)+(v.counts['반환 형식 오류']||0),v.calls,v.prompt_tokens,v.completion_tokens,v.status,v.sha,v.source,v.windows.map(w=>w.cycle+'회  '+w.text).join('\n\n')]),
 [34,13,9,12,14,8,8,8,14,16,16,22,67,60,90],{wrap:[14]});
const notsent=versions.filter(v=>v.final).flatMap(v=>v.unsent.map(q=>[labels[v.arm],task(v.task),q.cycle,q.by,q.why,q.question,q.source]));
sheet('전달 안 된 질문',['파이프라인','과제','회차','감시자','기록된 이유','감시자가 작성한 원문','원기록'],notsent,[34,14,9,12,33,92,69],{wrap:[5]});
sheet('초기 방식 재채점',['과거 실험','조건','시드','과제','모델','정답 /50','오답','보류','오류','질문 묶음','호출','토큰','비용 범위','제출 원기록',...Array.from({length:50},(_,i)=>'문항 '+(i+1))],
 hist.map(h=>[h.family,h.arm,h.seed,task(h.task),h.model,h.correct,h.wrong,h.defer,h.errors,h.windows,h.calls,h.tokens,h.cost_scope,h.source,
 ...cases.filter(c=>c.task===h.task).map(c=>{const v=h.items[c.id];return v.status+' '+show(v.actual)})]),[44,20,9,13,30,14,9,9,9,13,11,14,25,60,...Array(50).fill(17)]);
sheet('초기 질의응답',['과거 실험','조건','시드','과제','회차','제안자','질문 원문','기록된 답변','개별 답 연결 방식','원기록'],histQuestions.map(q=>[q.family,q.arm,q.seed,task(q.task),q.cycle,q.by,q.question,q.answer,q.mode,q.source]),[42,18,9,13,9,18,70,74,43,62],{wrap:[6,7]});
sheet('과거 실험 범위',['실험 폴더','비교 범위 또는 별도 기록 사유'],scope.map(v=>[v.folder,v.scope]),[52,97]);
wb.recalculate();
const observed=summary.getRange('D2:D'+(scores.length+1)).values.flat();
if(observed.some((x,i)=>x!==scores[i].correct))throw Error('점수 합산과 원기록이 다릅니다.');
const audited=await wb.inspect({kind:'region',sheetId:'구조별 결과',range:'A1:H5',maxChars:450});
if(!audited)throw Error('요약표를 읽을 수 없습니다.');
await fs.mkdir(preview,{recursive:true});
for(const [sheetName,range,key] of [['구조별 결과','A1:H8','summary'],['질문과 답변','D1:G3','qa']]){
 const pic=await wb.render({sheetName,range,scale:0.8,format:'png'});await fs.writeFile(path.join(preview,'sheet-'+key+'.png'),new Uint8Array(await pic.arrayBuffer()));
}
const out=path.join(base,'output','spreadsheets');await fs.mkdir(out,{recursive:true});
const exported=await SpreadsheetFile.exportXlsx(wb);
const workbookName='100문항_파이프라인_분석원자료.xlsx';
await exported.save(path.join(preview,workbookName));
await fs.copyFile(path.join(preview,workbookName),path.join(out,workbookName));

