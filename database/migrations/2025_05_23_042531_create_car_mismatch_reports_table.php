<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    /**
     * Run the migrations.
     */
    public function up(): void
    {
        Schema::create('car_mismatch_reports', function (Blueprint $table) {
            $table->id()->comment('아이디');
            $table->foreignId('user_id')->comment('신고자');
            $table->string('car_no')->comment('차량번호');
            $table->string('api_vin')->comment('조회차대번호');
            $table->string('scan_vin')->comment('스캔차대번호');
            $table->timestamps();
            $table->softDeletes();

            $table->foreign('user_id')->references('id')->on('users')->onDelete('cascade');
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::dropIfExists('car_mismatch_reports');
    }
};
