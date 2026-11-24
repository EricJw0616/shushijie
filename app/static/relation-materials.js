(function () {
  'use strict';

  const working = new WeakSet();

  function remember(hash, selection = {}) {
    const nextHash = hash || location.hash;
    if (nextHash !== location.hash) {
      AppHistory.restore(nextHash);
      const {view, arg} = parse(nextHash);
      state.lastHash = nextHash;
      state.curView = {view, arg};
    }
    history.replaceState({...history.state, relationSelection: selection}, '');
  }

  function selection() {
    return history.state?.relationSelection || {};
  }

  function savedContent(saved) {
    return `<p role="status">已加入「${esc(saved.title)}」的项目材料，可以回项目核对和选择。</p>
      <button type="button" class="btn sm ghost" data-relation-action="open-project" data-id="${esc(saved.id)}" data-kind="${esc(saved.kind)}">查看项目材料 →</button>`;
  }

  function render(edge) {
    if (!edge?.asset_id) {
      return edge?.material_unavailable_reason ? `<p class="relation-material-note">${esc(edge.material_unavailable_reason)}</p>` : '';
    }
    const project = workflowContext();
    const saved = history.state?.relationSaved;
    const form = `<button type="button" class="btn primary sm" data-relation-action="pick">${project ? '加入当前项目' : '加入项目'}</button>
      <p>${project ? `收集到「${esc(project.title)}」的项目材料，回项目后可决定是否采用。` : '把这条关系和原文出处收进项目材料。'}</p>
      <div data-relation-picker></div><p data-relation-feedback role="status" hidden></p>`;
    return `<div class="relation-material" data-relation-asset="${esc(edge.asset_id)}">${saved?.assetId === edge.asset_id ? savedContent(saved) : form}</div>`;
  }

  function feedback(panel, message, error = false) {
    const el = panel.querySelector('[data-relation-feedback]');
    if (!el) return;
    el.textContent = message;
    el.hidden = !message;
    el.classList.toggle('relation-material-error', error);
  }

  function setBusy(panel, busy) {
    if (busy) working.add(panel);
    else working.delete(panel);
    panel.setAttribute('aria-busy', String(busy));
    panel.querySelectorAll('button, input, select').forEach(el => { el.disabled = busy; });
  }

  function rememberSaved(panel, project) {
    const saved = {assetId: panel.dataset.relationAsset, id: project.id, kind: project.kind, title: project.title};
    if (panel.isConnected) {
      history.replaceState({...history.state, relationSaved: saved}, '');
      panel.innerHTML = savedContent(saved);
      panel.querySelector('button')?.focus({preventScroll: true});
    } else toast(`关系已加入「${project.title}」`);
  }

  async function saveExisting(panel, id) {
    if (working.has(panel)) return;
    const assetId = panel.dataset.relationAsset;
    const path = '/api/projects/' + encodeURIComponent(id);
    setBusy(panel, true);
    feedback(panel, '正在加入项目…');
    try {
      const latest = (await api(path)).project;
      if (!panel.isConnected) return;
      let project = latest;
      if (!(latest.items || []).some(item => item.asset_id === assetId)) {
        project = (await post(path, {action: 'add_asset', revision: latest.revision, asset_id: assetId})).project;
        if (project.kind === 'marketing') window.Studio?.advanceLocalDraftAfterRelation?.(id, latest.revision, project.revision);
      }
      rememberSaved(panel, project);
    } catch (error) {
      feedback(panel, error.message, true);
    } finally {
      setBusy(panel, false);
    }
  }

  async function showProjects(panel) {
    const picker = panel.querySelector('[data-relation-picker]');
    if (picker.firstElementChild) {
      picker.querySelector('select, input')?.focus();
      return;
    }
    setBusy(panel, true);
    feedback(panel, '正在读取项目…');
    try {
      const result = await api('/api/projects');
      if (!panel.isConnected) return;
      const projects = (result.projects || []).filter(project => project.status !== 'paused');
      const groups = [['editorial', '选题策划'], ['marketing', '营销策划']].map(([kind, label]) => {
        const options = projects.filter(project => project.kind === kind);
        return options.length ? `<optgroup label="${label}">${options.map(project => `<option value="${esc(project.id)}">${esc(project.title)}</option>`).join('')}</optgroup>` : '';
      }).join('');
      picker.innerHTML = `${groups ? `<form data-relation-form="existing">
        <label>选择已有项目<select name="project" required><option value="">请选择项目</option>${groups}</select></label>
        <button type="submit" class="btn primary sm">加入所选项目</button>
      </form>` : '<p>当前没有可加入的项目。</p>'}
      <div class="relation-material-actions">
        <button type="button" class="btn sm ghost" data-relation-action="new-project">新建选题策划</button>
        <button type="button" class="btn sm ghost" data-relation-action="cancel">取消</button>
      </div>`;
      panel.querySelector('[data-relation-action="pick"]').hidden = true;
      feedback(panel, '');
      picker.querySelector('select, button')?.focus({preventScroll: true});
    } catch (error) {
      feedback(panel, error.message, true);
    } finally {
      setBusy(panel, false);
    }
  }

  function showNewProject(panel) {
    const picker = panel.querySelector('[data-relation-picker]');
    picker.innerHTML = `<form data-relation-form="new">
      <label>选题主题<input name="topic" required maxlength="160" placeholder="例如，友谊导读"></label>
      <div class="relation-material-actions">
        <button type="submit" class="btn primary sm">创建并加入</button>
        <button type="button" class="btn sm ghost" data-relation-action="choose-project">返回选项目</button>
      </div>
    </form>`;
    feedback(panel, '');
    picker.querySelector('input')?.focus({preventScroll: true});
  }

  async function createProject(panel, topic) {
    if (working.has(panel)) return;
    if (!topic) { feedback(panel, '请填写选题主题。', true); return; }
    setBusy(panel, true);
    feedback(panel, '正在创建选题并保存材料…');
    try {
      const result = await post('/api/projects', {
        kind: 'editorial', title: topic, brief: {topic}, relation_asset_id: panel.dataset.relationAsset
      });
      rememberSaved(panel, result.project);
    } catch (error) {
      feedback(panel, error.message, true);
    } finally {
      setBusy(panel, false);
    }
  }

  document.addEventListener('click', event => {
    const button = event.target.closest('[data-relation-action]');
    const panel = button?.closest('[data-relation-asset]');
    if (!panel || working.has(panel)) return;
    switch (button.dataset.relationAction) {
      case 'pick': {
        const project = workflowContext();
        if (project) saveExisting(panel, project.id);
        else showProjects(panel);
        break;
      }
      case 'new-project':
        showNewProject(panel);
        break;
      case 'cancel': {
        panel.querySelector('[data-relation-picker]').innerHTML = '';
        const pick = panel.querySelector('[data-relation-action="pick"]');
        pick.hidden = false;
        pick.focus({preventScroll: true});
        feedback(panel, '');
        break;
      }
      case 'choose-project':
        panel.querySelector('[data-relation-picker]').innerHTML = '';
        panel.querySelector('[data-relation-action="pick"]').hidden = false;
        showProjects(panel);
        break;
      case 'open-project': {
        const {id, kind} = button.dataset;
        window.Studio?.prepareRelationMaterialList?.(id, panel.dataset.relationAsset);
        if (kind === 'marketing') go('campaigns', id, 'sources');
        else go('projects', id, 'materials');
        break;
      }
    }
  });

  document.addEventListener('submit', event => {
    const form = event.target.closest('[data-relation-form]');
    const panel = form?.closest('[data-relation-asset]');
    if (!panel) return;
    event.preventDefault();
    const values = new FormData(form);
    if (form.dataset.relationForm === 'new') createProject(panel, String(values.get('topic') || '').trim());
    else if (values.get('project')) saveExisting(panel, values.get('project'));
  });

  window.RelationMaterials = {render, remember, selection};
})();
