Component({
  props: {
    src: '',
    mode: 'aspectFill',
    lazyLoad: true,
    onLoad: () => {},
    onError: () => {},
  },
  data: {
    loaded: false,
    failed: false,
    renderSrc: '',
  },
  didMount() {
    this._source = this.props.src || '';
    this.setData({ renderSrc: this._source });
  },
  didUpdate() {
    const src = this.props.src || '';
    if (src !== this._source) {
      this._source = src;
      this.setData({ renderSrc: src, loaded: false, failed: false });
    }
  },
  methods: {
    handleLoad(e) {
      this.setData({ loaded: true, failed: false });
      if (typeof this.props.onLoad === 'function') this.props.onLoad(e);
    },
    handleError(e) {
      this.setData({ loaded: false, failed: true });
      if (typeof this.props.onError === 'function') this.props.onError(e);
    },
    retry() {
      const src = this.props.src || '';
      if (!src) return;
      this.setData({ renderSrc: '', loaded: false, failed: false });
      setTimeout(() => this.setData({ renderSrc: src }), 80);
    },
  },
});
