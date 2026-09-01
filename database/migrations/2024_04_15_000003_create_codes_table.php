<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('codes', function (Blueprint $table) {
            $table->id()->comment('아이디');
            $table->enum('type', ['ev', 'ice'])->comment('차종구분');
            $table->string('code')->comment('고장코드');
            $table->string('unit_name')->comment('유니트명');
            $table->string('unit_type')->nullable()->comment('유니트구분');
            $table->text('desc')->nullable()->comment('설명');
            $table->text('detail_desc')->nullable()->comment('상세설명');
            $table->text('root_cause')->nullable()->comment('주요원인');
            $table->text('howto_fix1')->nullable()->comment('조치방법1');
            $table->text('howto_fix2')->nullable()->comment('조치방법2');
            $table->text('howto_fix3')->nullable()->comment('조치방법3');
            $table->timestamps();
            $table->softDeletes();
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('codes');
    }
};
