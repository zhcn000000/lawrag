import { Line } from "@ant-design/charts";
import { CodeHighlighter, FileCard, Mermaid, Think } from "@ant-design/x";
import XMarkdown, { type ComponentProps, type XMarkdownProps } from "@ant-design/x-markdown";
import Latex from "@ant-design/x-markdown/plugins/Latex";
import { Infographic } from "@antv/infographic";
import { Skeleton } from "antd";
import { type FC, memo, type ReactNode, useEffect, useRef, useState } from "react";

type ReactInfographicProps = {
  children: ReactNode;
};

function ReactInfographic(props: ReactInfographicProps) {
  const { children } = props;

  const $container = useRef<HTMLDivElement>(null);
  const infographicInstance = useRef<Infographic>(null);

  useEffect(() => {
    if ($container.current) {
      infographicInstance.current = new Infographic({
        container: $container.current,
      });
    }

    return () => {
      infographicInstance.current?.destroy();
    };
  }, []);

  useEffect(() => {
    infographicInstance.current?.render(children as string);
  }, [children]);

  return <div ref={$container} />;
}

const CodeComponent: FC<ComponentProps> = (props) => {
  const { className, children } = props;
  const lang = className?.match(/language-(\w+)/)?.[1] || "";

  if (typeof children !== "string") return null;
  if (lang === "mermaid") return <Mermaid>{children}</Mermaid>;
  else if (lang === "infographic") return <ReactInfographic>{children}</ReactInfographic>;
  else return <CodeHighlighter lang={lang}>{children}</CodeHighlighter>;
};

const ThinkComponent = memo((props: ComponentProps) => {
  const [title, setTitle] = useState("Deep thinking...");
  const [loading, setLoading] = useState(true);
  const [expand, setExpand] = useState(true);

  useEffect(() => {
    if (props.streamStatus === "done") {
      setTitle("Complete thinking");
      setLoading(false);
      setExpand(false);
    }
  }, [props.streamStatus]);

  return (
    <Think title={title} loading={loading} expanded={expand} onClick={() => setExpand(!expand)}>
      {props.children}
    </Think>
  );
});

// biome-ignore lint/suspicious/noExplicitAny: <explanation> 需要兼容 Infographic 的数据格式</explanation>
const LineComponent = (props: Record<string, any>) => {
  const { children, axisXTitle, axisYTitle, streamStatus } = props;

  if (streamStatus === "loading") {
    return <Skeleton.Image active={true} style={{ width: 901, height: 408 }} />;
  }
  return <Line data={JSON.parse(children)} axisXTitle={axisXTitle} axisYTitle={axisYTitle} />;
};

// biome-ignore lint/suspicious/noExplicitAny: <explanation> 兼容 Markdown img 组件 props </explanation>
const ImageComponent = (props: Record<string, any>) => {
  const { src, alt } = props;
  return <FileCard name={alt || "image"} src={src} type="image" />;
};

// biome-ignore lint/suspicious/noExplicitAny: <explanation> 兼容 Markdown video 组件 props </explanation>
const VideoComponent = (props: Record<string, any>) => {
  const { src, alt } = props;
  return <FileCard name={alt || "video"} src={src} type="video" />;
};

// biome-ignore lint/suspicious/noExplicitAny: <explanation> 兼容 Markdown audio 组件 props </explanation>
const AudioComponent = (props: Record<string, any>) => {
  const { src, alt } = props;
  return <FileCard name={alt || "audio"} src={src} type="audio" />;
};
// biome-ignore lint/suspicious/noExplicitAny: <explanation> 兼容 Markdown a 组件 props </explanation>
const FileComponent = (props: Record<string, any>) => {
  const { href, children } = props;
  const name = typeof children === "string" ? children : "file";
  return <FileCard name={name} src={href} type="file" />;
};
export const SuperMarkdown = (props: XMarkdownProps) => {
  return (
    <XMarkdown
      {...props}
      components={{
        code: CodeComponent,
        think: ThinkComponent,
        customLine: LineComponent,
        img: ImageComponent,
        video: VideoComponent,
        audio: AudioComponent,
        a: FileComponent,
      }}
      config={{ extensions: Latex() }}
    />
  );
};
