package fvpu

trait ModuleGenerator {
  def generate(outputDir: String, args: Seq[String]): Unit
}
